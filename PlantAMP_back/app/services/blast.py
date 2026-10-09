"""
Busca por similaridade de sequência, com dois motores:

  smith-waterman  Alinhamento local exato (Biopython), BLOSUM62 + gap 11/1.
                  Sempre disponível; só precisa do pip install.
  blastp          O BLAST+ do NCBI (programa externo). Resultados iguais aos
                  do NCBI. Precisa estar instalado na máquina/servidor.
  auto            Usa o blastp se estiver instalado; senão, smith-waterman.

O motor padrão vem de BLAST_DEFAULT_ENGINE no .env; cada pedido pode escolher
outro no campo `engine`.

Para o blastp, a API monta sozinha o banco BLAST (makeblastdb) a partir da
tabela `peptides` e o refaz quando os peptídeos mudam.
"""
import functools
import hashlib
import math
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

import duckdb
from Bio.Align import PairwiseAligner, substitution_matrices

from app.core.config import settings

ENGINES = ("auto", "smith-waterman", "blastp")

_BLOSUM62 = substitution_matrices.load("BLOSUM62")
_PAM30 = substitution_matrices.load("PAM30")
_ALPHABET = set(_BLOSUM62.alphabet) - {"*"}
# U (selenocisteína) e O (pirrolisina) não estão nas matrizes
_REPLACE = str.maketrans({"U": "C", "O": "K", "J": "X"})
# Parâmetros de Karlin-Altschul do BLOSUM62 com gap 11/1 (tabela do NCBI)
_LAMBDA, _K = 0.267, 0.041
# Abaixo deste tamanho o blastp usa a tarefa "blastp-short" (como o site do NCBI)
SHORT_QUERY = 30


class InvalidSequence(ValueError):
    pass


class BlastBusy(RuntimeError):
    pass


class EngineUnavailable(RuntimeError):
    pass


class BlastFailed(RuntimeError):
    pass


# ======================================================================
# Sequências
# ======================================================================
def clean_sequence(raw: str) -> str:
    """Aceita texto puro ou FASTA; remove espaços, números e o '*' final."""
    lines = [ln for ln in raw.splitlines() if not ln.lstrip().startswith(">")]
    return re.sub(r"[\s\d*]", "", "".join(lines)).upper()


def normalize_query(raw: str) -> str:
    seq = clean_sequence(raw).translate(_REPLACE)
    if not seq:
        raise InvalidSequence("Informe uma sequência de aminoácidos.")
    invalid = sorted(set(seq) - _ALPHABET)
    if invalid:
        raise InvalidSequence(
            "Caracteres inválidos na sequência: " + ", ".join(invalid)
            + ". Use o código de uma letra dos aminoácidos (ex.: GLFDIVKKVVGALGSL)."
        )
    if len(seq) < settings.BLAST_MIN_QUERY_LENGTH:
        raise InvalidSequence(f"A sequência precisa ter pelo menos {settings.BLAST_MIN_QUERY_LENGTH} aminoácidos.")
    if len(seq) > settings.BLAST_MAX_QUERY_LENGTH:
        raise InvalidSequence(f"A sequência pode ter no máximo {settings.BLAST_MAX_QUERY_LENGTH} aminoácidos.")
    return seq


def _sanitize_subject(seq: str) -> str:
    """Sequência do banco pronta para alinhar: letras desconhecidas viram X."""
    seq = re.sub(r"[\s*]", "", (seq or "").upper()).translate(_REPLACE)
    return "".join(c if c in _ALPHABET else "X" for c in seq)


def _midline(qseq: str, sseq: str, matrix) -> tuple[str, int, int, int]:
    """Linha do meio: letra = idêntico, '+' = similar, espaço = diferente/gap."""
    mid, ident, pos, gaps = [], 0, 0, 0
    for a, b in zip(qseq, sseq):
        if a == "-" or b == "-":
            mid.append(" "); gaps += 1
        elif a == b and a != "X":
            mid.append(a); ident += 1; pos += 1
        elif a in matrix.alphabet and b in matrix.alphabet and matrix[a][b] > 0:
            mid.append("+"); pos += 1
        else:
            mid.append(" ")
    return "".join(mid), ident, pos, gaps


# ======================================================================
# Cache das sequências: só recarrega quando o banco muda (impressão digital
# calculada pelo próprio DuckDB). Não precisa mexer nas rotas de escrita.
# ======================================================================
_cache_lock = threading.Lock()
_cache: dict = {"fingerprint": None, "subjects": [], "residues": 0}


def _fingerprint(db) -> tuple:
    return tuple(db.execute(
        "SELECT count(*), coalesce(max(id), 0), coalesce(sum(hash(id::VARCHAR || ':' || sequence)), 0) "
        "FROM peptides"
    ).fetchone())


def _load_subjects(db) -> tuple[tuple, list[tuple[int, str]], int]:
    fp = _fingerprint(db)
    with _cache_lock:
        if _cache["fingerprint"] == fp:
            return fp, _cache["subjects"], _cache["residues"]
    rows = db.execute("SELECT id, sequence FROM peptides ORDER BY id").fetchall()
    subjects = [(pid, s) for pid, s in ((pid, _sanitize_subject(seq)) for pid, seq in rows) if s]
    residues = sum(len(s) for _, s in subjects)
    with _cache_lock:
        _cache.update(fingerprint=fp, subjects=subjects, residues=residues)
    return fp, subjects, residues


# ======================================================================
# Motor 1: Smith-Waterman (Biopython)
# ======================================================================
def _make_aligner() -> PairwiseAligner:
    aligner = PairwiseAligner()
    aligner.mode = "local"
    aligner.substitution_matrix = _BLOSUM62
    # No Biopython o "open" já conta a 1ª posição do gap: 11 + 1 = 12 => igual ao blastp 11/1
    aligner.open_gap_score = -12
    aligner.extend_gap_score = -1
    return aligner


def _aligned_strings(query: str, subject: str, aln) -> tuple[str, str, int, int, int, int]:
    """Monta query/subject alinhados (com '-') a partir dos blocos do Biopython."""
    q_blocks, s_blocks = aln.aligned
    qa, sa = [], []
    prev_q = prev_s = None
    for (qs, qe), (ss, se) in zip(q_blocks, s_blocks):
        qs, qe, ss, se = int(qs), int(qe), int(ss), int(se)
        if prev_q is not None:
            if qs > prev_q:
                qa.append(query[prev_q:qs]); sa.append("-" * (qs - prev_q))
            if ss > prev_s:
                qa.append("-" * (ss - prev_s)); sa.append(subject[prev_s:ss])
        qa.append(query[qs:qe]); sa.append(subject[ss:se])
        prev_q, prev_s = qe, se
    return ("".join(qa), "".join(sa), int(q_blocks[0][0]) + 1, int(q_blocks[-1][1]),
            int(s_blocks[0][0]) + 1, int(s_blocks[-1][1]))


def _run_smith_waterman(query: str, subjects, residues: int, max_evalue: float, limit: int) -> list[dict]:
    aligner = _make_aligner()  # um por chamada: thread-safe
    search_space = len(query) * max(residues, 1)
    ln2, lnk = math.log(2), math.log(_K)

    # 1) Só o score (rápido) para todo o banco
    scored = []
    for pid, seq in subjects:
        score = aligner.score(query, seq)
        if score <= 0:
            continue
        bits = (_LAMBDA * score - lnk) / ln2
        evalue = search_space * 2.0 ** (-bits)
        if evalue <= max_evalue:
            scored.append((score, bits, evalue, pid, seq))
    scored.sort(key=lambda t: (-t[0], t[3]))

    # 2) Alinhamento completo dos melhores
    hits = []
    for score, bits, evalue, pid, seq in scored[:limit]:
        qa, sa, qs, qe, ss, se = _aligned_strings(query, seq, next(iter(aligner.align(query, seq))))
        hits.append({"peptide_id": pid, "score": float(score), "bit_score": bits, "evalue": evalue,
                     "qseq": qa, "sseq": sa, "qstart": qs, "qend": qe, "sstart": ss, "send": se,
                     "slen": len(seq)})
    return hits


# ======================================================================
# Motor 2: BLAST+ do NCBI (blastp)
# ======================================================================
def _find_tool(name: str) -> Optional[str]:
    """Procura o programa em BLAST_BIN_DIR (se definido) ou no PATH."""
    if settings.BLAST_BIN_DIR:
        for candidate in (name, name + ".exe"):
            path = Path(settings.BLAST_BIN_DIR) / candidate
            if path.is_file():
                return str(path)
        return None
    return shutil.which(name)


@functools.lru_cache(maxsize=1)
def blastp_info() -> dict:
    """Detecta o BLAST+ uma vez por execução da API (reinicie após instalar)."""
    blastp, makeblastdb = _find_tool("blastp"), _find_tool("makeblastdb")
    if not blastp or not makeblastdb:
        missing = [n for n, p in (("blastp", blastp), ("makeblastdb", makeblastdb)) if not p]
        return {"available": False, "version": None,
                "detail": "Não encontrado: " + ", ".join(missing)
                          + ". Instale o BLAST+ e coloque no PATH (ou defina BLAST_BIN_DIR no .env)."}
    try:
        out = subprocess.run([blastp, "-version"], capture_output=True, text=True, timeout=15).stdout
        version = out.splitlines()[0].split(":", 1)[-1].strip() if out else None
    except (OSError, subprocess.SubprocessError) as e:
        return {"available": False, "version": None, "detail": f"Falha ao executar blastp: {e}"}
    return {"available": True, "version": version, "detail": None,
            "blastp": blastp, "makeblastdb": makeblastdb}


_db_lock = threading.Lock()
DB_NAME = "plantamp"  # nome relativo: evita problema do makeblastdb com espaços no caminho


def _ensure_blast_db(fp: tuple, subjects) -> Path:
    """Pasta com o banco BLAST da versão atual dos peptídeos (cria se precisar)."""
    base = Path(settings.BLAST_DB_DIR).resolve()
    name = "db_" + hashlib.sha256(repr(fp).encode()).hexdigest()[:16]
    target = base / name
    if (target / "READY").exists():
        return target
    with _db_lock:
        if (target / "READY").exists():
            return target
        base.mkdir(parents=True, exist_ok=True)
        tmp = base / f"tmp_{uuid.uuid4().hex}"
        tmp.mkdir()
        with open(tmp / f"{DB_NAME}.fasta", "w", encoding="ascii", newline="\n") as f:
            for pid, seq in subjects:
                f.write(f">pep_{pid}\n{seq}\n")
        proc = subprocess.run(
            [blastp_info()["makeblastdb"], "-in", f"{DB_NAME}.fasta", "-dbtype", "prot",
             "-out", DB_NAME, "-parse_seqids", "-title", "PlantAMP"],
            cwd=tmp, capture_output=True, text=True, timeout=settings.BLASTP_TIMEOUT_SECONDS,
        )
        if proc.returncode != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            raise BlastFailed("makeblastdb falhou: " + (proc.stderr or proc.stdout).strip()[:500])
        (tmp / "READY").write_text("ok")
        try:
            tmp.rename(target)
        except OSError:  # outro processo criou ao mesmo tempo
            shutil.rmtree(tmp, ignore_errors=True)
        # Apaga versões antigas do banco (e pastas temporárias abandonadas há mais de 1 h)
        now = time.time()
        for old in base.iterdir():
            if not old.is_dir() or old == target:
                continue
            if old.name.startswith("db_") or (old.name.startswith("tmp_") and now - old.stat().st_mtime > 3600):
                shutil.rmtree(old, ignore_errors=True)
    return target


_OUTFMT = "6 sseqid score bitscore evalue length qstart qend sstart send slen qseq sseq"
_PEP_ID = re.compile(r"pep_(\d+)")


def _run_blastp(query: str, fp: tuple, subjects, max_evalue: float, limit: int) -> tuple[list[dict], str, object]:
    info = blastp_info()
    task = "blastp-short" if len(query) < SHORT_QUERY else "blastp"
    db_dir = _ensure_blast_db(fp, subjects)
    cmd = [
        info["blastp"], "-task", task, "-db", DB_NAME, "-outfmt", _OUTFMT,
        "-evalue", str(max_evalue), "-max_target_seqs", str(limit), "-max_hsps", "1",
        "-num_threads", "1",
    ]
    try:
        proc = subprocess.run(cmd, input=f">query\n{query}\n", cwd=db_dir, capture_output=True,
                              text=True, timeout=settings.BLASTP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise BlastFailed("O blastp demorou demais e foi interrompido.")
    if proc.returncode != 0:
        raise BlastFailed("blastp falhou: " + (proc.stderr or proc.stdout).strip()[:500])

    hits, seen = [], set()
    for line in proc.stdout.splitlines():
        cols = line.rstrip("\n").split("\t")
        if len(cols) != 12:
            continue
        m = _PEP_ID.search(cols[0])
        if not m or int(m.group(1)) in seen:
            continue
        pid = int(m.group(1))
        seen.add(pid)
        hits.append({"peptide_id": pid, "score": float(cols[1]), "bit_score": float(cols[2]),
                     "evalue": float(cols[3]), "qstart": int(cols[5]), "qend": int(cols[6]),
                     "sstart": int(cols[7]), "send": int(cols[8]), "slen": int(cols[9]),
                     "qseq": cols[10], "sseq": cols[11]})
    hits.sort(key=lambda h: (-h["bit_score"], h["evalue"], h["peptide_id"]))
    matrix_desc = "PAM30, gap 9/1 (blastp-short)" if task == "blastp-short" else "BLOSUM62, gap 11/1 (blastp)"
    return hits, matrix_desc, (_PAM30 if task == "blastp-short" else _BLOSUM62)


# ======================================================================
# Ponto de entrada
# ======================================================================
def available_engines() -> dict:
    info = blastp_info()
    return {
        "default": settings.BLAST_DEFAULT_ENGINE,
        "resolved_default": resolve_engine(None),
        "engines": [
            {"name": "smith-waterman", "available": True, "version": None,
             "description": "Alinhamento local exato (Smith-Waterman, BLOSUM62, gap 11/1). Sempre disponível.",
             "detail": None},
            {"name": "blastp", "available": info["available"], "version": info["version"],
             "description": "BLAST+ do NCBI. Para sequências com menos de 30 aa usa blastp-short, como o site do NCBI.",
             "detail": info["detail"]},
        ],
    }


def resolve_engine(requested: Optional[str]) -> str:
    engine = requested or settings.BLAST_DEFAULT_ENGINE
    if engine == "auto":
        return "blastp" if blastp_info()["available"] else "smith-waterman"
    if engine == "blastp" and not blastp_info()["available"]:
        raise EngineUnavailable("O BLAST+ (blastp) não está instalado neste servidor. "
                                "Use engine = \"smith-waterman\" ou \"auto\".")
    return engine


# Limita BLASTs simultâneos: é a rota pública que mais usa CPU.
_slots = threading.BoundedSemaphore(max(1, settings.BLAST_MAX_CONCURRENT))


def blast(db: duckdb.DuckDBPyConnection, raw_query: str, *, engine: Optional[str], max_hits: int,
          max_evalue: float, min_identity: float, min_query_coverage: float) -> dict:
    query = normalize_query(raw_query)
    engine = resolve_engine(engine)
    # Pede mais candidatos que max_hits porque os filtros de identidade/cobertura vêm depois
    limit = min(max(max_hits * 4, 100), 5000)

    if not _slots.acquire(timeout=settings.BLAST_QUEUE_TIMEOUT_SECONDS):
        raise BlastBusy("Muitas buscas BLAST ao mesmo tempo. Tente novamente em instantes.")
    try:
        fp, subjects, residues = _load_subjects(db)
        if not subjects:
            raw_hits, matrix_desc, matrix = [], "-", _BLOSUM62
        elif engine == "blastp":
            raw_hits, matrix_desc, matrix = _run_blastp(query, fp, subjects, max_evalue, limit)
        else:
            raw_hits = _run_smith_waterman(query, subjects, residues, max_evalue, limit)
            matrix_desc, matrix = "BLOSUM62, gap 11/1", _BLOSUM62
    finally:
        _slots.release()

    hits = []
    for h in raw_hits:
        mid, ident, pos, gaps = _midline(h["qseq"], h["sseq"], matrix)
        length = len(h["qseq"])
        identity = 100.0 * ident / length if length else 0.0
        coverage = 100.0 * (h["qend"] - h["qstart"] + 1) / len(query)
        if identity < min_identity or coverage < min_query_coverage:
            continue
        hits.append({
            "peptide_id": h["peptide_id"], "score": h["score"], "bit_score": round(h["bit_score"], 1),
            "evalue": float(f"{h['evalue']:.2e}"), "identity": round(identity, 1),
            "positives": round(100.0 * pos / length, 1) if length else 0.0,
            "gaps": gaps, "alignment_length": length,
            "query_start": h["qstart"], "query_end": h["qend"],
            "subject_start": h["sstart"], "subject_end": h["send"], "subject_length": h["slen"],
            "query_coverage": round(coverage, 1),
            "query_aligned": h["qseq"], "midline": mid, "subject_aligned": h["sseq"],
        })
        if len(hits) >= max_hits:
            break

    # Dados dos peptídeos encontrados
    if hits:
        ids = [h["peptide_id"] for h in hits]
        cur = db.execute(
            f"""SELECT id, name, organism, activity, validation, uniprot, pdb, fonte
                FROM peptides WHERE id IN ({', '.join('?' for _ in ids)})""", ids)
        cols = [d[0] for d in cur.description]
        meta = {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}
        hits = [{**{k: v for k, v in h.items() if k != "peptide_id"}, "peptide": meta[h["peptide_id"]]}
                for h in hits if h["peptide_id"] in meta]

    return {
        "query": query, "query_length": len(query),
        "engine": engine,
        "engine_version": blastp_info()["version"] if engine == "blastp" else None,
        "matrix": matrix_desc, "database_sequences": len(subjects),
        "database_residues": residues, "hits": hits,
    }