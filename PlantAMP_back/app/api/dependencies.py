from dataclasses import dataclass, field
from typing import Iterator, Optional

import duckdb
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from app.core.security import decode_access_token
from app.db.connection import new_cursor
from app.services import accounts

# tokenUrl alimenta o botão "Authorize" do /docs (Swagger)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


def get_database() -> Iterator[duckdb.DuckDBPyConnection]:
    """Um cursor do DuckDB por requisição (seguro com várias threads)."""
    cursor = new_cursor()
    try:
        yield cursor
    finally:
        cursor.close()


def client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


@dataclass
class CurrentUser:
    id: int
    email: str
    full_name: Optional[str]
    groups: list[str] = field(default_factory=list)
    permissions: set[str] = field(default_factory=set)

    def can(self, permission: str) -> bool:
        return permission in self.permissions


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: duckdb.DuckDBPyConnection = Depends(get_database),
) -> CurrentUser:
    """
    Valida o token e recarrega usuário, grupos e permissões do banco A CADA
    requisição — mudar a matriz de acesso vale na hora, sem novo login.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Não autenticado ou sessão expirada.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise unauthorized

    payload = decode_access_token(token)
    if payload is None:
        raise unauthorized

    user = accounts.get_user_by_id(db, payload["sub"])
    if not user or not user["is_active"] or user["token_version"] != payload["ver"]:
        raise unauthorized

    return CurrentUser(
        id=user["id"],
        email=user["email"],
        full_name=user["full_name"],
        groups=accounts.get_user_groups(db, user["id"]),
        permissions=accounts.get_user_permissions(db, user["id"]),
    )


def require_permission(*codes: str):
    """
    Uso numa rota:
        user: CurrentUser = Depends(require_permission("peptides:import"))
    401 se não estiver logado, 403 se estiver logado mas sem a permissão.
    """
    def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not all(user.can(c) for c in codes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não tem permissão para esta ação.",
            )
        return user

    return checker
