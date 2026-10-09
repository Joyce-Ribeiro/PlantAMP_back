import os

import duckdb

from app.core.config import settings

if settings.MOTHERDUCK_TOKEN:
    # Conecta na nuvem (MotherDuck)
    db_connection = duckdb.connect(
        settings.DATABASE_FILE,
        config={"motherduck_token": settings.MOTHERDUCK_TOKEN},
    )
else:
    # Fallback para banco local caso esqueça o token
    folder = os.path.dirname(settings.DATABASE_FILE)
    if folder:
        os.makedirs(folder, exist_ok=True)
    db_connection = duckdb.connect(settings.DATABASE_FILE, read_only=False)


def get_db() -> duckdb.DuckDBPyConnection:
    """Conexão principal (usada no startup e no CLI)."""
    return db_connection


def new_cursor() -> duckdb.DuckDBPyConnection:
    """
    Cursor próprio por requisição. A conexão do DuckDB não é segura para
    várias threads ao mesmo tempo; cada requisição do FastAPI roda numa
    thread, então cada uma ganha o seu cursor.
    """
    return db_connection.cursor()
