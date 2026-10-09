"""APD (Antimicrobial Peptide Database) — https://aps.unmc.edu (seção "APD6" do notebook)."""
import re

import pandas as pd
from bs4 import BeautifulSoup

from coleta.comum import (NAO_ENCONTRADO, SEM_PUBMED, Resultado, SessaoPorThread, coletar, finalizar,
                          log)

NOME = "APD6"
SEARCH_URL = "https://aps.unmc.edu/database/result"
DETAIL_URL = "https://aps.unmc.edu/database/peptide"
WORKERS = 1       # servidor pequeno: uma requisição por vez, como no notebook
PAUSA = 0.3
TIMEOUT = 30

BUSCA = {
    "ID": "", "Name": "plants", "Name2": "", "Name3": "", "source": "",
    "Sequence": "", "Sequence2": "", "Length": "Any", "Netcharge": "Any",
    "HydrophobicPer": "Any", "Location": "Any", "LocationID": "",
    "Type": "Any", "Method": "Any", "info": "", "info2": "", "info3": "",
    "author": "", "Sort": "ID",
}

_PARTES_PLANTA = re.compile(r"^(seeds|leaves|whole plant|bark|roots|sap|latex|shoots),\s*", re.IGNORECASE)
_UNIPROT = re.compile(r"\b([OPQ][0-9A-Z]{5}|[A-NR-Z][0-9][A-Z0-9]{3}[0-9])\b")
_PDB = re.compile(r"\b([0-9][A-Za-z0-9]{3})\b")


def listar_ids(sessao) -> list[str]:
    r = sessao.post(SEARCH_URL, data=BUSCA, timeout=TIMEOUT)
    r.raise_for_status()
    ids = re.findall(r'name="peptides\[\]"\s+value="([A-Za-z0-9]+)"', r.text)
    return list(dict.fromkeys(ids))


def buscar(sessao, peptide_id: str):
    r = sessao.post(DETAIL_URL, data={"ID": peptide_id}, timeout=TIMEOUT)
    r.raise_for_status()
    tabela = BeautifulSoup(r.text, "html.parser").find("table", class_="peptide")
    if not tabela:
        return None
    dados = {"APD ID": peptide_id}
    for linha in tabela.find_all("tr"):
        cols = linha.find_all("td")
        if len(cols) != 2:
            continue
        chave = cols[0].get_text(strip=True).replace(":", "")
        if chave in ("Reference", "Additional info"):
            # o PubMed fica só no href dos links, então guardamos os links junto
            links = [a["href"] for a in cols[1].find_all("a", href=True)]
            dados[chave] = cols[1].get_text(" ", strip=True) + " " + " ".join(links)
        else:
            dados[chave] = cols[1].get_text(" ", strip=True)
    return dados if len(dados) > 1 else None


def _atividade(raw: str) -> str:
    if raw == NAO_ENCONTRADO:
        return NAO_ENCONTRADO
    achadas = set()
    for act in (a.strip() for a in re.split(r"[,&]", raw)):
        if "Gram" in act or "Antibacterial" in act:
            achadas.add("Antibacterial")
        elif "Antifungal" in act:
            achadas.add("Antifungal")
        elif "Antiviral" in act:
            achadas.add("Antiviral")
        elif "Antiparasitic" in act:
            achadas.add("Antiparasitic")
        elif "Antitumor" in act or "Antitumour" in act or "Cancer" in act:
            achadas.add("Antitumour")
        elif "Insect" in act:
            achadas.add("Insecticida")
    return ", ".join(sorted(achadas)) if achadas else NAO_ENCONTRADO


def _referencias(p: dict) -> tuple[str, str]:
    """reference e pubmed associados por posição, separados por " ## "."""
    raw_ref = p.get("Reference", NAO_ENCONTRADO)
    texto = raw_ref + " " + p.get("Additional info", "")
    ids = (re.findall(r"nih\.gov/(\d+)", texto, re.IGNORECASE)
           or re.findall(r"pubmed/(\d+)", texto, re.IGNORECASE)
           or re.findall(r"PubMed:\s*(\d+)", texto, re.IGNORECASE))
    ids = list(dict.fromkeys(ids))
    ref = re.sub(r"https?://\S+", "", raw_ref).replace("PubMed .", "").strip()
    if not ids:
        return ref or NAO_ENCONTRADO, SEM_PUBMED
    ref = ref or "Reference literature source"
    refs = [f"{ref} (Part {i + 1})" for i in range(len(ids))] if len(ids) > 1 else [ref]
    return " ## ".join(refs), " ## ".join(ids)


def _formatar(p: dict) -> dict:
    raw_name = p.get("Name/Class", NAO_ENCONTRADO)
    raw_org = p.get("Source", NAO_ENCONTRADO)
    swiss = p.get("SwissProt ID", p.get("Reference ID", NAO_ENCONTRADO))
    uni = _UNIPROT.search(swiss + " " + raw_name)
    pdb = _PDB.search(p.get("3D Structure", NAO_ENCONTRADO) + " " + swiss)
    nome_min = raw_name.lower()
    if raw_name == NAO_ENCONTRADO:
        validation = NAO_ENCONTRADO
    elif "predicted" in nome_min or "machine learning" in nome_min:
        validation = "Predicted"
    else:
        validation = "Experimentally Validated"
    reference, pubmed = _referencias(p)
    return {
        "name": raw_name.split("(")[0].strip() if raw_name != NAO_ENCONTRADO else NAO_ENCONTRADO,
        "sequence": p.get("Sequence", NAO_ENCONTRADO),
        "organism": _PARTES_PLANTA.sub("", raw_org).strip() if raw_org != NAO_ENCONTRADO else NAO_ENCONTRADO,
        "activity": _atividade(p.get("Activity", NAO_ENCONTRADO)),
        "validation": validation,
        "uniprot": uni.group(1) if uni else NAO_ENCONTRADO,
        "pdb": pdb.group(1).upper() if pdb else NAO_ENCONTRADO,
        "reference": reference,
        "pubmed": pubmed,
    }


def tratar(registros: list[dict]) -> pd.DataFrame:
    return finalizar(pd.DataFrame([_formatar(p) for p in registros]), NOME)


def executar(inicio: int = 1, limite: int = 0, workers: int = WORKERS):
    sessoes = SessaoPorThread()
    ids = listar_ids(sessoes.get())
    log.info("Busca no APD devolveu %d ids", len(ids))
    if not ids:
        return Resultado(), pd.DataFrame()
    if limite > 0:
        ids = ids[:limite]
    res = coletar(buscar, ids, sessoes, workers, pausa=PAUSA, progresso_a_cada=50)
    return res, tratar(res.registros) if res.registros else pd.DataFrame()