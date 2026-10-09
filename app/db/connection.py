import duckdb
import os
from app.core.config import settings

# Garante que a pasta 'data' exista antes de criar o banco
os.makedirs(os.path.dirname(settings.DATABASE_FILE), exist_ok=True)

# Conexão global mantida aberta para evitar locks de arquivo no DuckDB
db_connection = duckdb.connect(settings.DATABASE_FILE, read_only=False)

def get_db():
    return db_connection