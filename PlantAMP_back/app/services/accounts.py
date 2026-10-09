"""
Regras de negócio de contas e da matriz de acesso. Usado pelas rotas da API
e pelo CLI (python -m app.cli ...), para os dois seguirem as mesmas regras.
"""
from contextlib import contextmanager
from datetime import timedelta
from typing import Iterable, Optional
from urllib.parse import quote

import duckdb

from app.core.config import settings
from app.core.permissions import ADMIN_GROUP
from app.core.security import (
    generate_recovery_code,
    generate_reset_token,
    hash_password,
    hash_token,
    normalize_recovery_code,
    utcnow,
)

USER_FIELDS = (
    "id, email, full_name, password_hash, is_active, token_version, failed_logins, "
    "locked_until, last_login_at, password_changed_at, created_at"
)


class AccessRuleError(Exception):
    """Ação bloqueada por regra de segurança (ex.: remover o último admin)."""


@contextmanager
def transaction(db: duckdb.DuckDBPyConnection):
    db.execute("BEGIN TRANSACTION")
    try:
        yield
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise


def _row_to_dict(db: duckdb.DuckDBPyConnection, row) -> Optional[dict]:
    if row is None:
        return None
    return dict(zip([d[0] for d in db.description], row))


def normalize_email(email: str) -> str:
    return email.strip().lower()


# ----------------------------------------------------------------------
# Auditoria
# ----------------------------------------------------------------------
def audit(db, action: str, user_id: Optional[int] = None,
          detail: Optional[str] = None, ip: Optional[str] = None) -> None:
    db.execute(
        "INSERT INTO audit_log (user_id, action, detail, ip) VALUES (?, ?, ?, ?)",
        [user_id, action, detail, ip],
    )


# ----------------------------------------------------------------------
# Consultas
# ----------------------------------------------------------------------
def get_user_by_email(db, email: str) -> Optional[dict]:
    db.execute(f"SELECT {USER_FIELDS} FROM users WHERE email = ?", [normalize_email(email)])
    return _row_to_dict(db, db.fetchone())


def get_user_by_id(db, user_id: int) -> Optional[dict]:
    db.execute(f"SELECT {USER_FIELDS} FROM users WHERE id = ?", [user_id])
    return _row_to_dict(db, db.fetchone())


def get_user_groups(db, user_id: int) -> list[str]:
    rows = db.execute(
        """SELECT g.name FROM user_groups ug JOIN groups g ON g.id = ug.group_id
           WHERE ug.user_id = ? ORDER BY g.name""",
        [user_id],
    ).fetchall()
    return [r[0] for r in rows]


def get_user_permissions(db, user_id: int) -> set[str]:
    rows = db.execute(
        """SELECT DISTINCT gp.permission_code
           FROM user_groups ug JOIN group_permissions gp ON gp.group_id = ug.group_id
           WHERE ug.user_id = ?""",
        [user_id],
    ).fetchall()
    return {r[0] for r in rows}


def is_active_admin(db, user_id: int) -> bool:
    row = db.execute(
        """SELECT 1 FROM users u
           JOIN user_groups ug ON ug.user_id = u.id
           JOIN groups g ON g.id = ug.group_id
           WHERE u.id = ? AND u.is_active AND g.name = ?""",
        [user_id, ADMIN_GROUP],
    ).fetchone()
    return row is not None


def count_active_admins(db, exclude_user_id: Optional[int] = None) -> int:
    return db.execute(
        """SELECT COUNT(DISTINCT u.id) FROM users u
           JOIN user_groups ug ON ug.user_id = u.id
           JOIN groups g ON g.id = ug.group_id
           WHERE u.is_active AND g.name = ? AND u.id IS DISTINCT FROM ?""",
        [ADMIN_GROUP, exclude_user_id],
    ).fetchone()[0]


def ensure_not_last_admin(db, user_id: int) -> None:
    """Impede que o sistema fique sem nenhum admin ativo."""
    if is_active_admin(db, user_id) and count_active_admins(db, exclude_user_id=user_id) == 0:
        raise AccessRuleError(
            "Esta ação deixaria o sistema sem nenhum administrador ativo. "
            "Adicione outro admin antes."
        )


# ----------------------------------------------------------------------
# Escrita
# ----------------------------------------------------------------------
def _group_ids_by_name(db, names: Iterable[str]) -> dict[str, int]:
    names = sorted(set(names))
    if not names:
        return {}
    placeholders = ", ".join("?" for _ in names)
    rows = db.execute(f"SELECT name, id FROM groups WHERE name IN ({placeholders})", names).fetchall()
    found = dict(rows)
    missing = [n for n in names if n not in found]
    if missing:
        raise ValueError(f"Grupo(s) inexistente(s): {', '.join(missing)}")
    return found


def set_user_groups(db, user_id: int, group_names: Iterable[str]) -> None:
    """Define exatamente os grupos do usuário (só aplica a diferença)."""
    wanted = set(_group_ids_by_name(db, group_names).values())
    current = {r[0] for r in db.execute(
        "SELECT group_id FROM user_groups WHERE user_id = ?", [user_id]).fetchall()}
    for gid in current - wanted:
        db.execute("DELETE FROM user_groups WHERE user_id = ? AND group_id = ?", [user_id, gid])
    for gid in wanted - current:
        db.execute("INSERT INTO user_groups (user_id, group_id) VALUES (?, ?)", [user_id, gid])


def create_user(db, email: str, password: str, full_name: Optional[str] = None,
                group_names: Iterable[str] = ()) -> int:
    email = normalize_email(email)
    if get_user_by_email(db, email):
        raise ValueError("Já existe um usuário com este e-mail.")
    group_names = list(group_names)
    _group_ids_by_name(db, group_names)  # valida antes de inserir
    user_id = db.execute(
        """INSERT INTO users (email, full_name, password_hash, password_changed_at)
           VALUES (?, ?, ?, ?) RETURNING id""",
        [email, full_name, hash_password(password), utcnow()],
    ).fetchone()[0]
    set_user_groups(db, user_id, group_names)
    return user_id


def set_password(db, user_id: int, new_password: str) -> None:
    """
    Troca a senha, desbloqueia a conta, derruba todas as sessões abertas
    (token_version + 1) e invalida links de redefinição pendentes.
    """
    now = utcnow()
    db.execute(
        """UPDATE users SET password_hash = ?, token_version = token_version + 1,
               failed_logins = 0, locked_until = NULL, password_changed_at = ?
           WHERE id = ?""",
        [hash_password(new_password), now, user_id],
    )
    db.execute(
        "UPDATE password_reset_tokens SET used_at = ? WHERE user_id = ? AND used_at IS NULL",
        [now, user_id],
    )


def bump_token_version(db, user_id: int) -> None:
    db.execute("UPDATE users SET token_version = token_version + 1 WHERE id = ?", [user_id])


# ----------------------------------------------------------------------
# Bloqueio por tentativas
# ----------------------------------------------------------------------
def is_locked(user: dict) -> bool:
    return bool(user["locked_until"] and user["locked_until"] > utcnow())


def register_failed_attempt(db, user: dict) -> None:
    failed = (user["failed_logins"] or 0) + 1
    if failed >= settings.MAX_FAILED_LOGINS:
        db.execute(
            "UPDATE users SET failed_logins = 0, locked_until = ? WHERE id = ?",
            [utcnow() + timedelta(minutes=settings.LOCKOUT_MINUTES), user["id"]],
        )
    else:
        db.execute("UPDATE users SET failed_logins = ? WHERE id = ?", [failed, user["id"]])


def register_successful_login(db, user_id: int) -> None:
    db.execute(
        "UPDATE users SET failed_logins = 0, locked_until = NULL, last_login_at = ? WHERE id = ?",
        [utcnow(), user_id],
    )


# ----------------------------------------------------------------------
# Link de redefinição de senha
# ----------------------------------------------------------------------
def recent_reset_requests(db, user_id: int) -> int:
    return db.execute(
        """SELECT COUNT(*) FROM password_reset_tokens
           WHERE user_id = ? AND created_by IS NULL AND created_at > ?""",
        [user_id, utcnow() - timedelta(hours=1)],
    ).fetchone()[0]


def create_reset_token(db, user_id: int, created_by: Optional[int] = None) -> str:
    token = generate_reset_token()
    db.execute(
        """INSERT INTO password_reset_tokens (user_id, token_hash, expires_at, created_by, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        [user_id, hash_token(token),
         utcnow() + timedelta(minutes=settings.RESET_TOKEN_EXPIRE_MINUTES), created_by, utcnow()],
    )
    return token


def build_reset_link(token: str) -> str:
    # O token vai depois do "#": o navegador não o envia ao servidor nem em
    # logs de acesso nem no cabeçalho Referer.
    return f"{settings.ADMIN_BASE_URL.rstrip('/')}/admin/reset-password#token={quote(token)}"


def consume_reset_token(db, token: str) -> Optional[int]:
    """Valida e queima o token. Retorna o user_id ou None."""
    row = db.execute(
        """SELECT t.id, t.user_id FROM password_reset_tokens t
           JOIN users u ON u.id = t.user_id
           WHERE t.token_hash = ? AND t.used_at IS NULL AND t.expires_at > ? AND u.is_active""",
        [hash_token(token), utcnow()],
    ).fetchone()
    if not row:
        return None
    db.execute("UPDATE password_reset_tokens SET used_at = ? WHERE id = ?", [utcnow(), row[0]])
    return row[1]


# ----------------------------------------------------------------------
# Códigos de recuperação (backup offline)
# ----------------------------------------------------------------------
RECOVERY_CODES_COUNT = 10


def generate_recovery_codes(db, user_id: int) -> list[str]:
    """Gera 10 códigos novos e apaga os anteriores. Só são mostrados uma vez."""
    codes = [generate_recovery_code() for _ in range(RECOVERY_CODES_COUNT)]
    db.execute("DELETE FROM recovery_codes WHERE user_id = ?", [user_id])
    for code in codes:
        db.execute(
            "INSERT INTO recovery_codes (user_id, code_hash) VALUES (?, ?)",
            [user_id, hash_token(normalize_recovery_code(code))],
        )
    return codes


def remaining_recovery_codes(db, user_id: int) -> int:
    return db.execute(
        "SELECT COUNT(*) FROM recovery_codes WHERE user_id = ? AND used_at IS NULL", [user_id]
    ).fetchone()[0]


def consume_recovery_code(db, user_id: int, code: str) -> bool:
    row = db.execute(
        "SELECT id FROM recovery_codes WHERE user_id = ? AND code_hash = ? AND used_at IS NULL",
        [user_id, hash_token(normalize_recovery_code(code))],
    ).fetchone()
    if not row:
        return False
    db.execute("UPDATE recovery_codes SET used_at = ? WHERE id = ?", [utcnow(), row[0]])
    return True
