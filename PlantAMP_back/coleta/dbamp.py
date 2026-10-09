"""dbAMP — https://ycclab.cuhk.edu.cn/dbAMP (seção "dbAMP" do notebook)."""
import ssl

import pandas as pd
import urllib3
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

from coleta.comum import (NAO_ENCONTRADO, SEM_PUBMED, SessaoPorThread, coletar_faixa,
                          finalizar, limpar, mapear_atividades, nova_sessao, politica_retry,
                          preencher)

NOME = "dbAMP"
URL = "https://ycclab.cuhk.edu.cn/dbAMP/information.php"
ULTIMO_ID_CONHECIDO = 35600
WORKERS = 15
TIMEOUT = 30

ATIVIDADES = {
    "antibacterial": "Antibacterial",
    "antifungal": "Antifungal",
    "antiparasitic": "Antiparasitic",
    "antiviral": "Antiviral",
    "antitumour": "Antitumour",
    "anticancer": "Antitumour",
    "antimicrobial": "Antibacterial",
    "insecticidal": "Insecticida",
}


class _SSLAntigo(HTTPAdapter):
    """
    O servidor do dbAMP usa uma configuração TLS antiga que o Python atual
    recusa. Este adaptador baixa o nível de segurança SÓ para este site
    (mesma correção do notebook). Não use em outros lugares.
    """

    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def _sessao():
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    s = nova_sessao(_SSLAntigo(max_retries=politica_retry()))
    s.verify = False
    return s


def buscar(sessao, numero: int):
    pep_id = f"dbAMP_{numero:05d}"
    r = sessao.get(URL, params={"db": pep_id}, timeout=TIMEOUT)
    r.raise_for_status()
    aba = BeautifulSoup(r.text, "html.parser").find("div", id="home")
    tabela = aba.find("table", class_="table") if aba else None
    corpo = tabela.find("tbody") if tabela else None
    if not corpo:
        return None

    dados = {"dbAMP ID": pep_id}
    for linha in corpo.find_all("tr"):
        cols = linha.find_all("td")
        if len(cols) == 2:
            chave = cols[0].get_text(strip=True)
            # separator=", " evita colar palavras separadas por <br>/<span>
            valor = cols[1].get_text(separator=", ", strip=True).strip(", ")
            dados[chave] = valor or NAO_ENCONTRADO
    return dados if len(dados) > 1 else None


def _organismo(row) -> str:
    src = limpar(row.get("Source"))
    if src:
        return src
    tax = limpar(row.get("Taxonomy"))
    return tax.split(",")[-1].strip() if tax else NAO_ENCONTRADO


def _validation(v) -> str:
    return "Experimentally Validated" if preencher(v).upper() == "YES" else "Predicted"


def tratar(registros: list[dict]) -> pd.DataFrame:
    bruto = pd.DataFrame(registros)
    col = lambda nome: bruto.get(nome, pd.Series([None] * len(bruto), dtype=object))  # noqa: E731
    df = pd.DataFrame({
        "name": [limpar(r.get("Name")) or r.get("dbAMP ID") or NAO_ENCONTRADO for r in registros],
        "sequence": col("Sequence").map(preencher),
        "organism": [_organismo(r) for r in registros],
        "activity": col("Activity").map(lambda v: mapear_atividades(v, ATIVIDADES)),
        "validation": col("Experimental Evidence").map(_validation),
        "uniprot": col("UniprotKB ID/AC").map(preencher),
        "pdb": NAO_ENCONTRADO,
        "reference": NAO_ENCONTRADO,
        "pubmed": col("PubMed").map(lambda v: limpar(v) or SEM_PUBMED),
    })
    return finalizar(df, NOME)


def executar(inicio: int = 1, limite: int = 0, workers: int = WORKERS):
    res = coletar_faixa(buscar, SessaoPorThread(_sessao), inicio, ULTIMO_ID_CONHECIDO, workers, limite)
    return res, tratar(res.registros) if res.registros else pd.DataFrame()