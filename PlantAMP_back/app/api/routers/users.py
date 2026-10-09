from typing import List

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.dependencies import CurrentUser, client_ip, get_database, require_permission
from app.core.config import settings
from app.core.email import send_password_reset_email
from app.core.permissions import ADMIN_GROUP
from app.schemas.auth import MessageResponse
from app.schemas.user import ResetLinkResponse, UserCreate, UserResponse, UserUpdate
from app.services import accounts

router = APIRouter(prefix="/users", tags=["Users"])


# ----------------------------------------------------------------------
# Regras anti-escalada de privilégio
# ----------------------------------------------------------------------
def _check_can_grant(db, actor: CurrentUser, group_names) -> None:
    """Ninguém concede um grupo com permissões que ele mesmo não tem."""
    for name in set(group_names):
        if name == ADMIN_GROUP and ADMIN_GROUP not in actor.groups:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Só administradores mexem no grupo admin.")
        rows = db.execute(
            """SELECT gp.permission_code FROM groups g
               JOIN group_permissions gp ON gp.group_id = g.id WHERE g.name = ?""",
            [name],
        ).fetchall()
        extra = {r[0] for r in rows} - actor.permissions
        if extra:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"O grupo '{name}' tem permissões que você não possui: {', '.join(sorted(extra))}",
            )


def _protect_admin_target(db, actor: CurrentUser, target_id: int) -> None:
    """Só um admin pode alterar/resetar/excluir a conta de outro admin."""
    if ADMIN_GROUP in accounts.get_user_groups(db, target_id) and ADMIN_GROUP not in actor.groups:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Só administradores podem alterar contas de administradores.")


def _get_or_404(db, user_id: int) -> dict:
    user = accounts.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado.")
    return user


def _to_response(db, user: dict) -> UserResponse:
    return UserResponse(
        id=user["id"],
        email=user["email"],
        full_name=user["full_name"],
        is_active=user["is_active"],
        groups=accounts.get_user_groups(db, user["id"]),
        is_locked=accounts.is_locked(user),
        last_login_at=user["last_login_at"],
        password_changed_at=user["password_changed_at"],
        created_at=user["created_at"],
    )


# ----------------------------------------------------------------------
# Rotas
# ----------------------------------------------------------------------
@router.get("/", response_model=List[UserResponse])
def list_users(_: CurrentUser = Depends(require_permission("users:read")),
               db: duckdb.DuckDBPyConnection = Depends(get_database)):
    db.execute(f"SELECT {accounts.USER_FIELDS} FROM users ORDER BY id")
    cols = [d[0] for d in db.description]
    users = [dict(zip(cols, r)) for r in db.fetchall()]
    return [_to_response(db, u) for u in users]


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: int, _: CurrentUser = Depends(require_permission("users:read")),
             db: duckdb.DuckDBPyConnection = Depends(get_database)):
    return _to_response(db, _get_or_404(db, user_id))


@router.post("/", response_model=UserResponse, status_code=201)
def create_user(body: UserCreate, request: Request,
                actor: CurrentUser = Depends(require_permission("users:manage")),
                db: duckdb.DuckDBPyConnection = Depends(get_database)):
    _check_can_grant(db, actor, body.groups)
    try:
        with accounts.transaction(db):
            user_id = accounts.create_user(db, body.email, body.password, body.full_name, body.groups)
            accounts.audit(db, "user_created", actor.id, f"user_id={user_id} groups={body.groups}", client_ip(request))
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return _to_response(db, accounts.get_user_by_id(db, user_id))


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(user_id: int, body: UserUpdate, request: Request,
                actor: CurrentUser = Depends(require_permission("users:manage")),
                db: duckdb.DuckDBPyConnection = Depends(get_database)):
    user = _get_or_404(db, user_id)
    _protect_admin_target(db, actor, user_id)
    data = body.model_dump(exclude_unset=True)

    if user_id == actor.id and data.get("is_active") is False:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Você não pode desativar a sua própria conta.")

    current_groups = set(accounts.get_user_groups(db, user_id))
    new_groups = set(data["groups"]) if data.get("groups") is not None else current_groups
    _check_can_grant(db, actor, new_groups ^ current_groups)  # o que entra e o que sai

    loses_admin = ADMIN_GROUP in current_groups and ADMIN_GROUP not in new_groups
    if loses_admin or data.get("is_active") is False:
        try:
            accounts.ensure_not_last_admin(db, user_id)
        except accounts.AccessRuleError as e:
            raise HTTPException(status.HTTP_409_CONFLICT, str(e))

    try:
        with accounts.transaction(db):
            if "email" in data and data["email"] is not None:
                email = accounts.normalize_email(data["email"])
                other = accounts.get_user_by_email(db, email)
                if other and other["id"] != user_id:
                    raise ValueError("Já existe um usuário com este e-mail.")
                if email != user["email"]:
                    db.execute("UPDATE users SET email = ? WHERE id = ?", [email, user_id])
            if "full_name" in data:
                db.execute("UPDATE users SET full_name = ? WHERE id = ?", [data["full_name"], user_id])
            if data.get("is_active") is not None:
                db.execute("UPDATE users SET is_active = ? WHERE id = ?", [data["is_active"], user_id])
                if data["is_active"] is False:
                    accounts.bump_token_version(db, user_id)  # derruba as sessões dele
            if data.get("groups") is not None:
                accounts.set_user_groups(db, user_id, new_groups)
            accounts.audit(db, "user_updated", actor.id, f"user_id={user_id} fields={sorted(data)}", client_ip(request))
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return _to_response(db, accounts.get_user_by_id(db, user_id))


@router.post("/{user_id}/reset-link", response_model=ResetLinkResponse,
             summary="Gerar link de redefinição de senha para outro usuário")
def admin_reset_link(user_id: int, request: Request,
                     actor: CurrentUser = Depends(require_permission("users:manage")),
                     db: duckdb.DuckDBPyConnection = Depends(get_database)):
    """
    Recuperação 3: um admin ajuda outro que esqueceu a senha. O link também é
    enviado por e-mail ao usuário (se houver SMTP); o admin pode repassá-lo
    por outro canal seguro. Uso único, expira em RESET_TOKEN_EXPIRE_MINUTES.
    """
    user = _get_or_404(db, user_id)
    _protect_admin_target(db, actor, user_id)
    if not user["is_active"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Usuário inativo. Reative a conta primeiro.")
    token = accounts.create_reset_token(db, user_id, created_by=actor.id)
    db.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = ?", [user_id])
    link = accounts.build_reset_link(token)
    emailed = send_password_reset_email(user["email"], link)
    accounts.audit(db, "reset_link_by_admin", actor.id, f"user_id={user_id}", client_ip(request))
    return ResetLinkResponse(
        reset_link=link,
        expires_in_minutes=settings.RESET_TOKEN_EXPIRE_MINUTES,
        emailed=emailed,
        message="Link de uso único gerado. Repasse ao usuário por um canal seguro.",
    )


@router.post("/{user_id}/unlock", response_model=MessageResponse, summary="Desbloquear após muitas tentativas")
def unlock_user(user_id: int, request: Request,
                actor: CurrentUser = Depends(require_permission("users:manage")),
                db: duckdb.DuckDBPyConnection = Depends(get_database)):
    _get_or_404(db, user_id)
    _protect_admin_target(db, actor, user_id)
    db.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = ?", [user_id])
    accounts.audit(db, "user_unlocked", actor.id, f"user_id={user_id}", client_ip(request))
    return {"message": "Usuário desbloqueado."}


@router.delete("/{user_id}", response_model=MessageResponse)
def delete_user(user_id: int, request: Request,
                actor: CurrentUser = Depends(require_permission("users:manage")),
                db: duckdb.DuckDBPyConnection = Depends(get_database)):
    _get_or_404(db, user_id)
    if user_id == actor.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Você não pode excluir a sua própria conta.")
    _protect_admin_target(db, actor, user_id)
    try:
        accounts.ensure_not_last_admin(db, user_id)
    except accounts.AccessRuleError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    with accounts.transaction(db):
        for table in ("user_groups", "recovery_codes", "password_reset_tokens"):
            db.execute(f"DELETE FROM {table} WHERE user_id = ?", [user_id])
        db.execute("DELETE FROM users WHERE id = ?", [user_id])
        accounts.audit(db, "user_deleted", actor.id, f"user_id={user_id}", client_ip(request))
    return {"message": "Usuário excluído."}
