import duckdb
from app.db.connection import get_db

def create_tables():
    conn = get_db()
    
    # Criar sequence para ID auto-incremental
    try:
        conn.execute("CREATE SEQUENCE seq_peptides_id START 1;")
    except duckdb.CatalogException:
        pass # Ignora se a sequence já existir

    # Criar tabela de peptídeos
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