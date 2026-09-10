from app.db.connection import get_db

def get_database():
    """Injeta a conexão global do banco de dados nas rotas."""
    return get_db()