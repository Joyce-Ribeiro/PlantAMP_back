"""Peças compartilhadas pelos coletores: limpeza, sessão HTTP e coleta em paralelo."""
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("coleta")

# Colunas da tabela `peptides` (sem o id, que o banco gera)
COLUNAS = ["name", "sequence", "organism", "activity", "validation",
           "uniprot", "pdb", "reference", "pubmed", "fonte"]

NAO_ENCONTRADO = "Not found"
SEM_PUBMED = "Not available"

# Mesmo cabeçalho do notebook: alguns desses servidores recusam clientes "não navegador"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

_VAZIOS = {"", "NA", "--NA--", "NOT FOUND", "NONE", "NAN"}


# ----------------------------------------------------------------------
# Limpeza de valores
# ----------------------------------------------------------------------
def limpar(v) -> Optional[str]:
    """Texto limpo, ou None quando o valor é vazio/NA/--NA--/Not found."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    v = str(v).strip()
    return None if v.upper() in _VAZIOS else v


def preencher(v, padrao: str = NAO_ENCONTRADO) -> str:
    v = limpar(v)
    return padrao if v is None else v


def mapear_atividades(texto, mapa: dict[str, str]) -> str:
    """Procura cada chave do mapa no texto (sem diferenciar maiúsculas) e junta os rótulos."""
    texto = limpar(texto)
    if texto is None:
        return NAO_ENCONTRADO
    texto = texto.lower()
    achadas = {rotulo for chave, rotulo in mapa.items() if chave in texto}
    return ", ".join(sorted(achadas)) if achadas else NAO_ENCONTRADO


def finalizar(df: pd.DataFrame, fonte: str) -> pd.DataFrame:
    """
    Regras finais iguais para todas as fontes:
    - sequência sem espaços e obrigatória; nome obrigatório
    - sequência única (fica a primeira ocorrência)
    - todas as colunas da tabela, na ordem certa, com `fonte` preenchida
    """
    df = df.copy()
    for col in COLUNAS:
        if col not in df.columns:
            df[col] = NAO_ENCONTRADO
    df["fonte"] = fonte
    df["sequence"] = df["sequence"].map(lambda s: re.sub(r"\s+", "", str(s)) if limpar(s) else NAO_ENCONTRADO)
    df = df[(df["sequence"] != NAO_ENCONTRADO) & (df["name"] != NAO_ENCONTRADO)]
    df = df.drop_duplicates(subset=["sequence"], keep="first")
    return df[COLUNAS].reset_index(drop=True)


# ----------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------
def politica_retry() -> Retry:
    """Tenta de novo em queda de conexão, 429 e 5xx (1s, 2s, 4s, 8s)."""
    return Retry(total=4, connect=4, read=4, backoff_factor=1,
                 status_forcelist=(429, 500, 502, 503, 504),
                 allowed_methods=frozenset({"GET", "POST"}), raise_on_status=False)


def nova_sessao(adapter: Optional[HTTPAdapter] = None) -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    adapter = adapter or HTTPAdapter(max_retries=politica_retry())
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


class SessaoPorThread:
    """requests.Session não é garantidamente segura entre threads: uma por thread."""

    def __init__(self, fabrica: Callable[[], requests.Session] = nova_sessao):
        self._fabrica = fabrica
        self._local = threading.local()

    def get(self) -> requests.Session:
        if not hasattr(self._local, "s"):
            self._local.s = self._fabrica()
        return self._local.s


# ----------------------------------------------------------------------
# Coleta em paralelo
# ----------------------------------------------------------------------
@dataclass
class Resultado:
    registros: list = field(default_factory=list)  # o que veio das páginas
    tentados: int = 0
    inexistentes: int = 0   # páginas que existem mas não têm o registro
    falhas: list = field(default_factory=list)      # (id, erro) após todas as tentativas

    @property
    def taxa_falha(self) -> float:
        return len(self.falhas) / self.tentados if self.tentados else 0.0


def coletar(buscar: Callable, ids: Iterable, sessoes: SessaoPorThread, workers: int,
            pausa: float = 0.0, resultado: Optional[Resultado] = None,
            progresso_a_cada: int = 500) -> Resultado:
    """
    Chama buscar(sessao, id) para cada id. buscar devolve:
      - None            -> registro inexistente
      - dict            -> um registro
      - list[dict]      -> vários registros
      - levanta exceção -> falha (contada; não interrompe a coleta)
    """
    res = resultado or Resultado()
    ids = list(ids)
    total = len(ids)

    def tarefa(i):
        try:
            return i, buscar(sessoes.get(), i), None
        except Exception as e:  # noqa: BLE001 — uma página quebrada não para a coleta
            return i, None, e
        finally:
            if pausa:
                time.sleep(pausa)

    feitos = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for fut in as_completed([ex.submit(tarefa, i) for i in ids]):
            i, dado, erro = fut.result()
            res.tentados += 1
            feitos += 1
            if erro is not None:
                res.falhas.append((i, f"{type(erro).__name__}: {erro}"))
            elif not dado:
                res.inexistentes += 1
            elif isinstance(dado, list):
                res.registros.extend(dado)
            else:
                res.registros.append(dado)
            if feitos % progresso_a_cada == 0 or feitos == total:
                log.info("  %d/%d processados | registros: %d | falhas: %d",
                         feitos, total, len(res.registros), len(res.falhas))
    return res


def coletar_faixa(buscar: Callable, sessoes: SessaoPorThread, inicio: int, ultimo_conhecido: int,
                  workers: int, limite: int = 0, parar_apos_vazios: int = 50) -> Resultado:
    """
    Coleta ids numéricos de `inicio` até `ultimo_conhecido` e depois continua
    em blocos até achar `parar_apos_vazios` ids seguidos sem registro. Assim
    os ids novos que a fonte publicar entram sem mexer no código.
    Com `limite` > 0 (teste), coleta só os primeiros `limite` ids e não procura novos.
    """
    if limite > 0:
        log.info("Modo teste: só os ids %d a %d", inicio, inicio + limite - 1)
        return coletar(buscar, range(inicio, inicio + limite), sessoes, workers)

    fim = max(inicio, ultimo_conhecido)
    log.info("Coletando ids %d a %d", inicio, fim)
    res = coletar(buscar, range(inicio, fim + 1), sessoes, workers)

    proximo = fim + 1
    while True:
        bloco = range(proximo, proximo + parar_apos_vazios)
        antes = len(res.registros)
        log.info("Procurando ids novos: %d a %d", bloco.start, bloco.stop - 1)
        coletar(buscar, bloco, sessoes, workers, resultado=res, progresso_a_cada=10**9)
        if len(res.registros) == antes:
            break
        proximo = bloco.stop
    return res