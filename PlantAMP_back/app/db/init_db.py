import duckdb

from app.core.permissions import ADMIN_GROUP, DEFAULT_GROUPS, PERMISSIONS
from app.db.connection import get_db


def _create_sequence(conn: duckdb.DuckDBPyConnection, name: str) -> None:
    try:
        conn.execute(f"CREATE SEQUENCE {name} START 1;")
    except duckdb.CatalogException:
        pass  # já existe


def create_tables() -> None:
    conn = get_db()

    # ------------------------------------------------------------------
    # Peptídeos (igual ao que já existia)
    # ------------------------------------------------------------------
    _create_sequence(conn, "seq_peptides_id")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS peptides (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_peptides_id'),
            name VARCHAR NOT NULL,
            sequence VARCHAR NOT NULL UNIQUE,
            organism VARCHAR NOT NULL,
            activity VARCHAR NOT NULL,
            validation VARCHAR NOT NULL,
            uniprot VARCHAR DEFAULT 'Not found',
            pdb VARCHAR DEFAULT 'Not found',
            reference VARCHAR NOT NULL,
            pubmed VARCHAR NOT NULL,
            fonte VARCHAR
        )
    """)

    # ------------------------------------------------------------------
    # Usuários
    # ------------------------------------------------------------------
    _create_sequence(conn, "seq_users_id")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_users_id'),
            email VARCHAR NOT NULL UNIQUE,          -- sempre minúsculo
            full_name VARCHAR,
            password_hash VARCHAR NOT NULL,         -- Argon2id
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            token_version INTEGER NOT NULL DEFAULT 0,  -- sobe => derruba sessões
            failed_logins INTEGER NOT NULL DEFAULT 0,
            locked_until TIMESTAMP,
            last_login_at TIMESTAMP,
            password_changed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """)

    # ------------------------------------------------------------------
    # Matriz de acesso: grupos × permissões, usuários × grupos
    # ------------------------------------------------------------------
    _create_sequence(conn, "seq_groups_id")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_groups_id'),
            name VARCHAR NOT NULL UNIQUE,
            description VARCHAR,
            is_system BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS permissions (
            code VARCHAR PRIMARY KEY,
            description VARCHAR
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS group_permissions (
            group_id INTEGER NOT NULL,
            permission_code VARCHAR NOT NULL,
            PRIMARY KEY (group_id, permission_code)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_groups (
            user_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            PRIMARY KEY (user_id, group_id)
        )
    """)

    # ------------------------------------------------------------------
    # Recuperação de senha
    # ------------------------------------------------------------------
    _create_sequence(conn, "seq_reset_tokens_id")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_reset_tokens_id'),
            user_id INTEGER NOT NULL,
            token_hash VARCHAR NOT NULL UNIQUE,     -- SHA-256 do token do link
            expires_at TIMESTAMP NOT NULL,
            used_at TIMESTAMP,
            created_by INTEGER,                     -- NULL = pedido pelo próprio usuário
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """)
    _create_sequence(conn, "seq_recovery_codes_id")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recovery_codes (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_recovery_codes_id'),
            user_id INTEGER NOT NULL,
            code_hash VARCHAR NOT NULL,             -- SHA-256 do código
            used_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """)

    # ------------------------------------------------------------------
    # Auditoria (quem fez o quê)
    # ------------------------------------------------------------------
    _create_sequence(conn, "seq_audit_id")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_audit_id'),
            user_id INTEGER,
            action VARCHAR NOT NULL,
            detail VARCHAR,
            ip VARCHAR,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """)

    seed_access_matrix(conn)


def seed_access_matrix(conn: duckdb.DuckDBPyConnection) -> None:
    """
    Sincroniza o catálogo de permissões do código com o banco e garante que
    o grupo `admin` exista com todas as permissões. NÃO cria usuários —
    o primeiro admin é criado pelo terminal: python -m app.cli create-admin
    """
    # Permissões do catálogo
    for code, description in PERMISSIONS.items():
        exists = conn.execute("SELECT 1 FROM permissions WHERE code = ?", [code]).fetchone()
        if exists:
            conn.execute("UPDATE permissions SET description = ? WHERE code = ?", [description, code])
        else:
            conn.execute("INSERT INTO permissions (code, description) VALUES (?, ?)", [code, description])

    # Remove permissões que saíram do código
    codes = list(PERMISSIONS)
    placeholders = ", ".join("?" for _ in codes)
    conn.execute(f"DELETE FROM group_permissions WHERE permission_code NOT IN ({placeholders})", codes)
    conn.execute(f"DELETE FROM permissions WHERE code NOT IN ({placeholders})", codes)

    # Grupos padrão (só cria se não existir)
    for name, cfg in DEFAULT_GROUPS.items():
        row = conn.execute("SELECT id FROM groups WHERE name = ?", [name]).fetchone()
        if row:
            continue
        group_id = conn.execute(
            "INSERT INTO groups (name, description, is_system) VALUES (?, ?, ?) RETURNING id",
            [name, cfg["description"], cfg["is_system"]],
        ).fetchone()[0]
        for code in cfg["permissions"]:
            conn.execute(
                "INSERT INTO group_permissions (group_id, permission_code) VALUES (?, ?)",
                [group_id, code],
            )

    # Admin sempre com TODAS as permissões (inclusive as novas)
    admin_id = conn.execute("SELECT id FROM groups WHERE name = ?", [ADMIN_GROUP]).fetchone()[0]
    conn.execute("UPDATE groups SET is_system = TRUE WHERE id = ?", [admin_id])
    for code in PERMISSIONS:
        has = conn.execute(
            "SELECT 1 FROM group_permissions WHERE group_id = ? AND permission_code = ?",
            [admin_id, code],
        ).fetchone()
        if not has:
            conn.execute(
                "INSERT INTO group_permissions (group_id, permission_code) VALUES (?, ?)",
                [admin_id, code],
            )
