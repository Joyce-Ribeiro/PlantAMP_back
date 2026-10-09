"""
Páginas da área administrativa — separadas do site público.

    /admin/login             login dos administradores
    /admin/forgot-password   pedir link de redefinição por e-mail
    /admin/reset-password    criar nova senha a partir do link
    /admin/recovery          redefinir senha com código de recuperação
    /admin                   painel (matriz de acesso, usuários, códigos)

O HTML é estático; quem protege os dados é a API (token + permissões).
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

ADMIN_DIR = Path(__file__).resolve().parents[2] / "static" / "admin"

PAGES = {
    "": "panel.html",
    "login": "login.html",
    "forgot-password": "forgot-password.html",
    "reset-password": "reset-password.html",
    "recovery": "recovery.html",
}

router = APIRouter(prefix="/admin", include_in_schema=False)


@router.get("")
@router.get("/")
def admin_panel():
    return FileResponse(ADMIN_DIR / PAGES[""])


@router.get("/{page}")
def admin_page(page: str):
    filename = PAGES.get(page)
    if not filename:
        raise HTTPException(status_code=404)
    return FileResponse(ADMIN_DIR / filename)
