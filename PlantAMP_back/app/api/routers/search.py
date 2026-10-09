"""
Busca PÚBLICA (sem login): autocomplete, busca por atributos e BLAST.

    GET  /api/search/fields         campos que têm autocomplete
    GET  /api/search/suggest        sugestões de um campo enquanto o usuário digita
    GET  /api/search/suggest-all    sugestões de vários campos (caixa de busca única)
    GET  /api/search/peptides       busca com filtros combinados + paginação
    GET  /api/search/blast/engines  motores de BLAST disponíveis (smith-waterman / blastp)
    POST /api/search/blast          alinhamento de uma sequência contra o banco
"""
import logging
from typing import List, Literal, Optional, get_args

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_database
from app.schemas.search import (
    BlastEnginesResponse,
    BlastRequest,
    BlastResponse,
    PeptideSearchResponse,
    SuggestAllResponse,
    SuggestField,
    SuggestResponse,
)
from app.services import blast as blast_svc
from app.services import search as svc

router = APIRouter(prefix="/search", tags=["Busca"])
logger = logging.getLogger("plantamp.search")

# Escritos por extenso para o Pylance/mypy entenderem. Se mudar SUGGEST_FIELDS
# ou SORTS em app/services/search.py, atualize aqui também: a verificação
# abaixo derruba a API no start se as listas ficarem diferentes.
FieldName = Literal["name", "organism", "activity", "validation", "fonte", "uniprot", "pdb", "pubmed"]
SortName = Literal["id", "name", "organism", "activity", "length"]

if set(get_args(FieldName)) != set(svc.SUGGEST_FIELDS):
    raise RuntimeError("FieldName (routers/search.py) diferente de SUGGEST_FIELDS (services/search.py)")
if set(get_args(SortName)) != set(svc.SORTS):
    raise RuntimeError("SortName (routers/search.py) diferente de SORTS (services/search.py)")


@router.get("/fields", response_model=List[SuggestField], summary="Campos com autocomplete")
def suggest_fields():
    return [{"field": f, "label": c["label"]} for f, c in svc.SUGGEST_FIELDS.items()]


@router.get("/suggest", response_model=SuggestResponse, summary="Autocomplete de um campo")
def suggest(
    field: FieldName = Query(..., description="Campo a sugerir (veja /search/fields)"),
    q: str = Query("", max_length=100, description="O que o usuário já digitou. Vazio = valores mais comuns"),
    limit: int = Query(10, ge=1, le=50),
    db: duckdb.DuckDBPyConnection = Depends(get_database),
):
    """
    Devolve valores que existem no banco para o campo, do mais relevante para o
    menos: igual ao digitado, começa com, alguma palavra começa com, contém.
    Ignora maiúsculas/minúsculas e acentos. `count` = quantos peptídeos têm o valor.
    """
    items = svc.suggest(db, field, q, limit)
    return {"field": field, "label": svc.SUGGEST_FIELDS[field]["label"], "query": q, "items": items}


@router.get("/suggest-all", response_model=SuggestAllResponse,
            summary="Autocomplete em vários campos de uma vez")
def suggest_all(
    q: str = Query("", max_length=100),
    limit: int = Query(5, ge=1, le=20, description="Máximo de sugestões por campo"),
    fields: Optional[List[FieldName]] = Query(None, description="Padrão: nome, organismo, atividade, fonte, validação"),
    db: duckdb.DuckDBPyConnection = Depends(get_database),
):
    """Para uma caixa de busca única: sugestões agrupadas por campo. Grupos sem resultado são omitidos."""
    result = svc.suggest_all(db, q, limit, list(dict.fromkeys(fields)) if fields else None)
    groups = [
        {"field": f, "label": svc.SUGGEST_FIELDS[f]["label"], "query": q, "items": items}
        for f, items in result.items() if items
    ]
    return {"query": q, "groups": groups}


@router.get("/peptides", response_model=PeptideSearchResponse, summary="Buscar peptídeos por atributos")
def search_peptides(
    q: Optional[str] = Query(None, max_length=200, description="Texto livre em nome, organismo, atividade, fonte, UniProt, PDB e sequência"),
    name: Optional[str] = Query(None, max_length=200),
    organism: Optional[str] = Query(None, max_length=200),
    activity: Optional[str] = Query(None, max_length=200),
    validation: Optional[str] = Query(None, max_length=200),
    fonte: Optional[str] = Query(None, max_length=200),
    uniprot: Optional[str] = Query(None, max_length=50),
    pdb: Optional[str] = Query(None, max_length=50),
    pubmed: Optional[str] = Query(None, max_length=50),
    sequence_contains: Optional[str] = Query(None, max_length=200, description="Motivo/trecho exato da sequência (ex.: KKVV)"),
    min_length: Optional[int] = Query(None, ge=1, description="Tamanho mínimo da sequência (aa)"),
    max_length: Optional[int] = Query(None, ge=1, description="Tamanho máximo da sequência (aa)"),
    sort: SortName = Query("id"),
    order: Literal["asc", "desc"] = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    db: duckdb.DuckDBPyConnection = Depends(get_database),
):
    """
    Todos os filtros são combinados com AND e ignoram maiúsculas/minúsculas e
    acentos (o valor só precisa estar contido no campo). Use junto com o
    autocomplete: o usuário escolhe uma sugestão e o front manda o valor aqui.
    """
    if min_length and max_length and min_length > max_length:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "min_length não pode ser maior que max_length.")
    total, items = svc.search_peptides(
        db, q=q,
        filters={"name": name, "organism": organism, "activity": activity, "validation": validation,
                 "fonte": fonte, "uniprot": uniprot, "pdb": pdb, "pubmed": pubmed},
        sequence_contains=sequence_contains, min_length=min_length, max_length=max_length,
        sort=sort, order=order, page=page, page_size=page_size,
    )
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/blast/engines", response_model=BlastEnginesResponse, summary="Motores de BLAST disponíveis")
def blast_engines():
    """Use no front para mostrar a escolha de motor só quando o blastp estiver instalado."""
    return blast_svc.available_engines()


@router.post("/blast", response_model=BlastResponse, summary="BLAST: alinhar uma sequência contra o banco")
def blast(body: BlastRequest, db: duckdb.DuckDBPyConnection = Depends(get_database)):
    """
    Compara a sequência com todos os peptídeos do banco. Aceita texto puro ou FASTA.

    - `engine = "smith-waterman"`: alinhamento local exato (BLOSUM62, gap 11/1).
    - `engine = "blastp"`: BLAST+ do NCBI (precisa estar instalado no servidor).
      Sequências com menos de 30 aa usam blastp-short (PAM30), como o site do NCBI.
    - `engine = "auto"`: blastp se instalado, senão smith-waterman.

    O campo `engine` da resposta diz qual motor rodou. Resultados ordenados por
    score; quanto menor o E-value, mais significativo.
    """
    try:
        return blast_svc.blast(
            db, body.sequence, engine=body.engine, max_hits=body.max_hits, max_evalue=body.max_evalue,
            min_identity=body.min_identity, min_query_coverage=body.min_query_coverage,
        )
    except blast_svc.InvalidSequence as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    except (blast_svc.BlastBusy, blast_svc.EngineUnavailable) as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e), headers={"Retry-After": "5"})
    except blast_svc.BlastFailed as e:
        logger.error("BLAST falhou: %s", e)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Erro ao executar o BLAST. Veja o log do servidor.")