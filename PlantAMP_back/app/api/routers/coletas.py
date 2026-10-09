"""
Disparo das coletas de dados (GitHub Actions) a partir da API.

    GET  /api/coletas/          fontes disponíveis + última execução de cada uma
    POST /api/coletas/{fonte}   dispara o workflow .github/workflows/coleta-{fonte}.yml

O token do GitHub fica só no .env do servidor (GITHUB_TOKEN). O navegador
nunca o vê: o painel chama esta API, que confere login e permissão
(`coletas:run`), registra na auditoria e só então fala com o GitHub.
"""
import json
import urllib.error
import urllib.request
from typing import Optional
from urllib.parse import quote

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.dependencies import CurrentUser, client_ip, get_database, require_permission
from app.core.config import settings
from app.schemas.coleta import (ColetaDisparadaResponse, ColetaRequest, ColetasResponse,
                                ExecucaoResponse, FonteColetaResponse)
from app.services.accounts import audit

router = APIRouter(prefix="/coletas", tags=["Coletas de dados"])

# Precisa bater com os arquivos .github/workflows/coleta-<fonte>.yml
FONTES = {
    "plantpepdb": ("PlantPepDB", "Peptídeos de plantas (14.139.61.8/PlantPepDB). Coleta completa: ~10 min."),
    "dbamp": ("dbAMP", "Peptídeos antimicrobianos (ycclab.cuhk.edu.cn/dbAMP). Coleta completa: ~2h30."),
    "apd": ("APD6", "Antimicrobial Peptide Database (aps.unmc.edu), busca 'plants'. Coleta completa: ~5 min."),
}
EM_ANDAMENTO = {"queued", "in_progress", "waiting", "requested", "pending"}
GITHUB_API = "https://api.github.com"


class GitHubError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _configurado() -> bool:
    return bool(settings.GITHUB_TOKEN and settings.GITHUB_REPO)


def _workflow(fonte: str) -> str:
    return f"coleta-{fonte}.yml"


def _github(method: str, path: str, body: Optional[dict] = None):
    req = urllib.request.Request(
        GITHUB_API + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "PlantAMP-API",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raise GitHubError(e.code, _explicar(e.code)) from None
    except (urllib.error.URLError, TimeoutError):
        raise GitHubError(0, "Não foi possível falar com o GitHub agora. Tente de novo em instantes.") from None


def _explicar(code: int) -> str:
    return {
        401: "O GitHub recusou o GITHUB_TOKEN (inválido ou expirado). Gere outro e atualize o .env.",
        403: "O GITHUB_TOKEN não tem a permissão 'Actions: Read and write' neste repositório.",
        404: "Workflow não encontrado. Confira GITHUB_REPO no .env e se os arquivos .github/workflows/coleta-*.yml "
             "estão na branch GITHUB_REF.",
        422: "O GitHub não aceitou o disparo (a branch GITHUB_REF existe? o workflow tem workflow_dispatch?).",
    }.get(code, f"Erro do GitHub ({code}).")


def _ultima_execucao(fonte: str) -> Optional[ExecucaoResponse]:
    repo = quote(settings.GITHUB_REPO, safe="/")
    data = _github("GET", f"/repos/{repo}/actions/workflows/{_workflow(fonte)}/runs?per_page=1")
    runs = (data or {}).get("workflow_runs") or []
    if not runs:
        return None
    r = runs[0]
    return ExecucaoResponse(status=r.get("status") or "unknown", conclusion=r.get("conclusion"),
                            titulo=r.get("display_title"), evento=r.get("event"),
                            criado_em=r.get("created_at"), url=r.get("html_url") or "")


def _fonte_ou_404(fonte: str) -> str:
    if fonte not in FONTES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Fonte desconhecida. Use: {', '.join(FONTES)}.")
    return fonte


def _exigir_config():
    if not _configurado():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Coletas não configuradas: defina GITHUB_TOKEN e GITHUB_REPO no .env do servidor.")


# ----------------------------------------------------------------------
# Rotas
# ----------------------------------------------------------------------
@router.get("/", response_model=ColetasResponse, summary="Fontes de coleta e a última execução de cada uma")
def listar_coletas(_: CurrentUser = Depends(require_permission("coletas:run"))):
    fontes = []
    for fonte, (nome, descricao) in FONTES.items():
        item = FonteColetaResponse(fonte=fonte, nome=nome, descricao=descricao)
        if _configurado():
            try:
                item.ultima_execucao = _ultima_execucao(fonte)
            except GitHubError as e:
                item.erro = str(e)
        fontes.append(item)
    repo = settings.GITHUB_REPO if _configurado() else None
    return ColetasResponse(configurado=_configurado(), repositorio=repo,
                           actions_url=f"https://github.com/{repo}/actions" if repo else None, fontes=fontes)


@router.post("/{fonte}", response_model=ColetaDisparadaResponse, status_code=status.HTTP_202_ACCEPTED,
             summary="Disparar a coleta de uma fonte (roda no GitHub Actions)")
def disparar_coleta(fonte: str, request: Request, body: Optional[ColetaRequest] = None,
                    user: CurrentUser = Depends(require_permission("coletas:run")),
                    db: duckdb.DuckDBPyConnection = Depends(get_database)):
    fonte = _fonte_ou_404(fonte)
    _exigir_config()
    body = body or ColetaRequest()
    repo = quote(settings.GITHUB_REPO, safe="/")
    actions_url = f"https://github.com/{settings.GITHUB_REPO}/actions/workflows/{_workflow(fonte)}"

    try:
        ultima = _ultima_execucao(fonte)
        if ultima and ultima.status in EM_ANDAMENTO:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Já existe uma coleta {FONTES[fonte][0]} em andamento. Aguarde ela terminar.")
        _github("POST", f"/repos/{repo}/actions/workflows/{_workflow(fonte)}/dispatches", {
            "ref": settings.GITHUB_REF,
            # inputs do workflow_dispatch vão sempre como texto
            "inputs": {"modo": body.modo, "inicio": str(body.inicio), "limite": str(body.limite)},
        })
    except GitHubError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))

    audit(db, "coleta_disparada", user.id,
          f"fonte={fonte} modo={body.modo} inicio={body.inicio} limite={body.limite}", client_ip(request))
    return ColetaDisparadaResponse(
        message=f"Coleta {FONTES[fonte][0]} enviada ao GitHub Actions (modo {body.modo}). "
                "Ela aparece na lista em alguns segundos.",
        acompanhar=actions_url,
    )