"""PlantPepDB — http://14.139.61.8/PlantPepDB (seção "PlantPepDB" do notebook)."""
import io
from urllib.parse import urljoin

import pandas as pd
from bs4 import BeautifulSoup

from coleta.comum import (NAO_ENCONTRADO, SEM_PUBMED, SessaoPorThread, coletar_faixa,
                          finalizar, limpar, mapear_atividades, preencher)

NOME = "PlantPepDB"
BASE = "http://14.139.61.8/PlantPepDB/pages/"
ULTIMO_ID_CONHECIDO = 6172   # maior id visto na última coleta; os novos são descobertos sozinhos
WORKERS = 15
TIMEOUT = 20

ATIVIDADES = {
    "antibacterial": "Antibacterial",
    "antifungal": "Antifungal",
    "antiparasitic": "Antiparasitic",
    "antitumour": "Antitumour",
    "anticancer": "Antitumour",
    "antiviral": "Antiviral",
    "insect": "Insecticida",
}


def buscar(sessao, numero: int):
    """Abre a página do peptídeo, acha o link de download e lê o TSV."""
    pagina = sessao.get(urljoin(BASE, "information.php"), params={"id": f"PPepDB_{numero}"}, timeout=TIMEOUT)
    pagina.raise_for_status()
    link = BeautifulSoup(pagina.text, "html.parser").find(
        "a", href=lambda h: h and "download_info.php" in h)
    if not link:
        return None
    arquivo = sessao.get(urljoin(BASE, link["href"]), timeout=TIMEOUT)
    arquivo.raise_for_status()
    if not arquivo.text.strip():
        return None
    df = pd.read_csv(io.StringIO(arquivo.text), sep="\t", dtype=str)
    return df.to_dict("records") or None


def _validation(v) -> str:
    v = preencher(v).lower()
    if "experimental" in v:
        return "Experimentally Validated"
    if "predict" in v or "homology" in v:
        return "Predicted"
    return NAO_ENCONTRADO


def tratar(registros: list[dict]) -> pd.DataFrame:
    bruto = pd.DataFrame(registros)
    col = lambda nome: bruto.get(nome, pd.Series([None] * len(bruto), dtype=object))  # noqa: E731
    df = pd.DataFrame({
        "name": col("Peptide Name").map(preencher),
        "sequence": col("Sequence").map(preencher),
        "organism": col("Plant source").map(preencher),
        "activity": col("Peptide function").map(lambda v: mapear_atividades(v, ATIVIDADES)),
        "validation": col("Validation").map(_validation),
        "uniprot": NAO_ENCONTRADO,
        "pdb": NAO_ENCONTRADO,
        "reference": NAO_ENCONTRADO,
        "pubmed": col("PMID").map(lambda v: limpar(v) or SEM_PUBMED),
    })
    return finalizar(df, NOME)


def executar(inicio: int = 1, limite: int = 0, workers: int = WORKERS):
    res = coletar_faixa(buscar, SessaoPorThread(), inicio, ULTIMO_ID_CONHECIDO, workers, limite)
    return res, tratar(res.registros) if res.registros else pd.DataFrame()