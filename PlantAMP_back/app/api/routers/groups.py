from typing import List

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.dependencies import CurrentUser, client_ip, get_database, require_permission
from app.schemas.auth import MessageResponse
from app.schemas.group import (
    AccessMatrixResponse,
    GroupCreate,
    GroupPermissionsUpdate,
    GroupResponse,
    GroupUpdate,
    PermissionResponse,
)
from app.services import accounts

router = APIRouter(prefix="/groups", tags=["Groups / Matriz de acesso"])


def _all_permission_codes(db) -> list[str]:
    return [r[0] for r in db.execute("SELECT code FROM permissions ORDER BY code").fetchall()]


def _validate_permissions(db, actor: CurrentUser, codes: list[str]) -> set[str]:
    codes = set(codes)
    unknown = codes - set(_all_permission_codes(db))
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Permissão inexistente: {', '.join(sorted(unknown))}")
    # Anti-escalada: só concede o que você mesmo tem
    beyond = codes - actor.permissions
    if beyond:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"Você não pode conceder permissões que não possui: {', '.join(sorted(beyond))}")
    return codes


def _get_group_or_404(db, group_id: int) -> dict:
    row = db.execute("SELECT id, name, description, is_system FROM groups WHERE id = ?", [group_id]).fetchone()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grupo não encontrado.")
    return dict(zip(["id", "name", "description", "is_system"], row))


def _group_response(db, group_id: int) -> GroupResponse:
    g = _get_group_or_404(db, group_id)
    perms = [r[0] for r in db.execute(
        "SELECT permission_code FROM group_permissions WHERE group_id = ? ORDER BY 1", [group_id]).fetchall()]
    members = db.execute("SELECT COUNT(*) FROM user_groups WHERE group_id = ?", [group_id]).fetchone()[0]
    return GroupResponse(**g, permissions=perms, member_count=members)


# ----------------------------------------------------------------------
# Leitura
# ----------------------------------------------------------------------
@router.get("/permissions", response_model=List[PermissionResponse], summary="Catálogo de permissões")
def list_permissions(_: CurrentUser = Depends(require_permission("groups:read")),
                     db: duckdb.DuckDBPyConnection = Depends(get_database)):
    rows = db.execute("SELECT code, description FROM permissions ORDER BY code").fetchall()
    return [{"code": c, "description": d} for c, d in rows]


@router.get("/matrix", response_model=AccessMatrixResponse, summary="Matriz de acesso (grupos × permissões)")
def access_matrix(_: CurrentUser = Depends(require_permission("groups:read")),
                  db: duckdb.DuckDBPyConnection = Depends(get_database)):
    perms = db.execute("SELECT code, description FROM permissions ORDER BY code").fetchall()
    codes = [p[0] for p in perms]
    groups = db.execute("SELECT id, name, is_system FROM groups ORDER BY is_system DESC, name").fetchall()
    granted = set(db.execute("SELECT group_id, permission_code FROM group_permissions").fetchall())
    return {
        "permissions": [{"code": c, "description": d} for c, d in perms],
        "rows": [
            {"group_id": gid, "group": name, "is_system": is_system,
             "permissions": {c: (gid, c) in granted for c in codes}}
            for gid, name, is_system in groups
        ],
    }


@router.get("/", response_model=List[GroupResponse])
def list_groups(_: CurrentUser = Depends(require_permission("groups:read")),
                db: duckdb.DuckDBPyConnection = Depends(get_database)):
    ids = [r[0] for r in db.execute("SELECT id FROM groups ORDER BY is_system DESC, name").fetchall()]
    return [_group_response(db, gid) for gid in ids]


@router.get("/{group_id}", response_model=GroupResponse)
def get_group(group_id: int, _: CurrentUser = Depends(require_permission("groups:read")),
              db: duckdb.DuckDBPyConnection = Depends(get_database)):
    return _group_response(db, group_id)


# ----------------------------------------------------------------------
# Escrita
# ----------------------------------------------------------------------
@router.post("/", response_model=GroupResponse, status_code=201)
def create_group(body: GroupCreate, request: Request,
                 actor: CurrentUser = Depends(require_permission("groups:manage")),
                 db: duckdb.DuckDBPyConnection = Depends(get_database)):
    if db.execute("SELECT 1 FROM groups WHERE name = ?", [body.name]).fetchone():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Já existe um grupo com este nome.")
    codes = _validate_permissions(db, actor, body.permissions)
    with accounts.transaction(db):
        gid = db.execute("INSERT INTO groups (name, description) VALUES (?, ?) RETURNING id",
                         [body.name, body.description]).fetchone()[0]
        for c in codes:
            db.execute("INSERT INTO group_permissions (group_id, permission_code) VALUES (?, ?)", [gid, c])
        accounts.audit(db, "group_created", actor.id, f"{body.name}: {sorted(codes)}", client_ip(request))
    return _group_response(db, gid)


@router.patch("/{group_id}", response_model=GroupResponse)
def update_group(group_id: int, body: GroupUpdate, request: Request,
                 actor: CurrentUser = Depends(require_permission("groups:manage")),
                 db: duckdb.DuckDBPyConnection = Depends(get_database)):
    g = _get_group_or_404(db, group_id)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != g["name"]:
        if g["is_system"]:
            raise HTTPException(status.HTTP_409_CONFLICT, "Grupos de sistema não podem ser renomeados.")
        if db.execute("SELECT 1 FROM groups WHERE name = ?", [data["name"]]).fetchone():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Já existe um grupo com este nome.")
        db.execute("UPDATE groups SET name = ? WHERE id = ?", [data["name"], group_id])
    if "description" in data:
        db.execute("UPDATE groups SET description = ? WHERE id = ?", [data["description"], group_id])
    accounts.audit(db, "group_updated", actor.id, f"group_id={group_id}", client_ip(request))
    return _group_response(db, group_id)


@router.put("/{group_id}/permissions", response_model=GroupResponse,
            summary="Definir as permissões do grupo (uma linha da matriz)")
def set_group_permissions(group_id: int, body: GroupPermissionsUpdate, request: Request,
                          actor: CurrentUser = Depends(require_permission("groups:manage")),
                          db: duckdb.DuckDBPyConnection = Depends(get_database)):
    g = _get_group_or_404(db, group_id)
    if g["is_system"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "O grupo admin sempre tem todas as permissões.")
    wanted = _validate_permissions(db, actor, body.permissions)
    current = {r[0] for r in db.execute(
        "SELECT permission_code FROM group_permissions WHERE group_id = ?", [group_id]).fetchall()}
    # Também impede REMOVER permissões que você não tem (não mexe no que não controla)
    removing_beyond = (current - wanted) - actor.permissions
    if removing_beyond:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"Você não pode remover permissões que não possui: {', '.join(sorted(removing_beyond))}")
    with accounts.transaction(db):
        for c in current - wanted:
            db.execute("DELETE FROM group_permissions WHERE group_id = ? AND permission_code = ?", [group_id, c])
        for c in wanted - current:
            db.execute("INSERT INTO group_permissions (group_id, permission_code) VALUES (?, ?)", [group_id, c])
        accounts.audit(db, "group_permissions_set", actor.id, f"{g['name']}: {sorted(wanted)}", client_ip(request))
    return _group_response(db, group_id)


@router.delete("/{group_id}", response_model=MessageResponse)
def delete_group(group_id: int, request: Request,
                 actor: CurrentUser = Depends(require_permission("groups:manage")),
                 db: duckdb.DuckDBPyConnection = Depends(get_database)):
    g = _get_group_or_404(db, group_id)
    if g["is_system"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Grupos de sistema não podem ser excluídos.")
    with accounts.transaction(db):
        db.execute("DELETE FROM group_permissions WHERE group_id = ?", [group_id])
        db.execute("DELETE FROM user_groups WHERE group_id = ?", [group_id])
        db.execute("DELETE FROM groups WHERE id = ?", [group_id])
        accounts.audit(db, "group_deleted", actor.id, g["name"], client_ip(request))
    return {"message": f"Grupo '{g['name']}' excluído."}
