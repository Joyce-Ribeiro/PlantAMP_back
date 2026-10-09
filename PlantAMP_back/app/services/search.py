"""
Busca pública de peptídeos: autocomplete e busca por atributos.

- Autocomplete: sugere valores que JÁ EXISTEM no banco, ordenados por
  relevância (igual > começa com > palavra começa com > contém) e frequência.
  Ignora maiúsculas/minúsculas e acentos.
- Busca por atributos: filtros combináveis + paginação.
- BLAST: fica em app/services/blast.py.
"""
from typing import Optional

import duckdb

from app.services.blast import clean_sequence

# ======================================================================
# Autocomplete
# ======================================================================
# Campos liberados para sugestão. A chave é a coluna da tabela `peptides`
# (lista fechada => seguro interpolar no SQL).
#   split: o campo guarda vários valores numa célula ("Antibacterial; Antifungal")
#          e cada um vira uma sugestão separada.
#   exclude: valores que nunca são sugeridos.
SUGGEST_FIELDS: dict[str, dict] = {
    "name":       {"label": "Nome",       "split": False},
    "organism":   {"label": "Organismo",  "split": False},
    "activity":   {"label": "Atividade",  "split": True},
    "validation": {"label": "Validação",  "split": False},
    "fonte":      {"label": "Fonte",      "split": False},
    "uniprot":    {"label": "UniProt",    "split": False, "exclude": ["Not found"]},
    "pdb":        {"label": "PDB",        "split": False, "exclude": ["Not found"]},
    "pubmed":     {"label": "PubMed",     "split": False},
}
# Campos usados pela caixa de busca única (/search/suggest-all)
SUGGEST_ALL_FIELDS = ["name", "organism", "activity", "fonte", "validation"]
# Separadores de valores múltiplos (para os campos com split=True)
SPLIT_REGEX = r"\s*[,;|]\s*"


def _norm_sql(expr: str) -> str:
    """Normalização usada dos dois lados: sem acento, minúsculo, sem espaços nas pontas."""
    return f"lower(strip_accents(trim({expr})))"


def _suggest_sql(field: str, q: str) -> tuple[str, list]:
    """
    SQL que devolve (field, value, n, rank) para um campo. Valores iguais
    ignorando caixa/acentos são juntados, mostrando a grafia mais comum.
    """
    cfg = SUGGEST_FIELDS[field]
    params: list = []
    if cfg["split"]:
        source = (f"SELECT trim(unnest(string_split_regex({field}, ?))) AS value "
                  f"FROM peptides WHERE {field} IS NOT NULL")
        params.append(SPLIT_REGEX)
    else:
        source = f"SELECT trim({field}) AS value FROM peptides WHERE {field} IS NOT NULL"

    where = ["value <> ''"]
    for ex in cfg.get("exclude", []):
        where.append(f"{_norm_sql('value')} <> {_norm_sql('?')}")
        params.append(ex)

    qn = q.strip()
    if qn:
        where.append(f"contains({_norm_sql('value')}, {_norm_sql('?')})")
        params.append(qn)
        rank = (
            f"CASE WHEN key = {_norm_sql('?')} THEN 0 "
            f"WHEN starts_with(key, {_norm_sql('?')}) THEN 1 "
            f"WHEN contains(' ' || key, ' ' || {_norm_sql('?')}) THEN 2 "
            f"ELSE 3 END"
        )
        rank_params = [qn, qn, qn]
    else:
        rank, rank_params = "0", []

    sql = f"""
        SELECT '{field}' AS field, value, n, {rank} AS rank FROM (
            SELECT {_norm_sql('value')} AS key, arg_max(value, n) AS value, sum(n)::INTEGER AS n
            FROM (
                SELECT value, count(*) AS n FROM ({source}) v
                WHERE {' AND '.join(where)}
                GROUP BY value
            ) exact_values
            GROUP BY key
        ) grouped
    """
    # O CASE do rank aparece ANTES no texto do SQL, então seus parâmetros vêm primeiro
    return sql, rank_params + params


_ORDER = "ORDER BY rank, n DESC, length(value), value"


def suggest(db: duckdb.DuckDBPyConnection, field: str, q: str, limit: int) -> list[dict]:
    sql, params = _suggest_sql(field, q)
    rows = db.execute(f"SELECT value, n FROM ({sql}) s {_ORDER} LIMIT ?", params + [limit]).fetchall()
    return [{"value": v, "count": n} for v, n in rows]


def suggest_all(db: duckdb.DuckDBPyConnection, q: str, limit: int,
                fields: Optional[list[str]] = None) -> dict[str, list[dict]]:
    """Sugestões de vários campos numa única consulta (uma ida só ao MotherDuck)."""
    fields = fields or SUGGEST_ALL_FIELDS
    parts, params = [], []
    for f in fields:
        sql, p = _suggest_sql(f, q)
        parts.append(f"SELECT * FROM ({sql})")
        params += p
    rows = db.execute(
        f"""SELECT field, value, n FROM ({' UNION ALL '.join(parts)}) s
            QUALIFY row_number() OVER (PARTITION BY field {_ORDER}) <= ?
            ORDER BY field, rank, n DESC, length(value), value""",
        params + [limit],
    ).fetchall()
    out: dict[str, list[dict]] = {f: [] for f in fields}
    for field, value, n in rows:
        out[field].append({"value": value, "count": n})
    return out


# ======================================================================
# Busca por atributos
# ======================================================================
PEPTIDE_COLUMNS = ["id", "name", "sequence", "organism", "activity", "validation",
                   "uniprot", "pdb", "reference", "pubmed", "fonte"]
TEXT_FILTERS = ["name", "organism", "activity", "validation", "fonte", "uniprot", "pdb", "pubmed"]
GLOBAL_SEARCH_COLUMNS = ["name", "organism", "activity", "fonte", "uniprot", "pdb", "sequence"]
SORTS = {
    "id": "id", "name": "lower(name)", "organism": "lower(organism)",
    "activity": "lower(activity)", "length": "length(sequence)",
}


def search_peptides(db: duckdb.DuckDBPyConnection, *, q: Optional[str], filters: dict[str, Optional[str]],
                    sequence_contains: Optional[str], min_length: Optional[int], max_length: Optional[int],
                    sort: str, order: str, page: int, page_size: int) -> tuple[int, list[dict]]:
    where, params = ["1=1"], []

    def contains(col: str, value: str):
        where.append(f"contains({_norm_sql(col)}, {_norm_sql('?')})")
        params.append(value)

    for col in TEXT_FILTERS:
        value = (filters.get(col) or "").strip()
        if value:
            contains(col, value)

    if q and q.strip():
        ors = " OR ".join(
            "contains(" + _norm_sql("coalesce(" + c + ", '')") + ", " + _norm_sql("?") + ")"
            for c in GLOBAL_SEARCH_COLUMNS
        )
        where.append(f"({ors})")
        params += [q.strip()] * len(GLOBAL_SEARCH_COLUMNS)

    if sequence_contains:
        motif = clean_sequence(sequence_contains)
        if motif:
            where.append("contains(upper(sequence), ?)")
            params.append(motif)
    if min_length is not None:
        where.append("length(sequence) >= ?")
        params.append(min_length)
    if max_length is not None:
        where.append("length(sequence) <= ?")
        params.append(max_length)

    direction = "DESC" if order == "desc" else "ASC"
    sql = f"""
        SELECT {', '.join(PEPTIDE_COLUMNS)}, length(sequence) AS length, count(*) OVER () AS _total
        FROM peptides WHERE {' AND '.join(where)}
        ORDER BY {SORTS[sort]} {direction}, id {direction}
        LIMIT ? OFFSET ?
    """
    cur = db.execute(sql, params + [page_size, (page - 1) * page_size])
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    if rows:
        total = rows[0]["_total"]
    else:
        # Página além do fim: ainda informa o total
        total = db.execute(f"SELECT count(*) FROM peptides WHERE {' AND '.join(where)}", params).fetchone()[0]
    for r in rows:
        r.pop("_total", None)
    return total, rows