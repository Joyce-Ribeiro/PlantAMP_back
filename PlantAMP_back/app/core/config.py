from typing import List, Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Plantamp Backend"
    VERSION: str = "1.0.0"
    DATABASE_FILE: str = "md:plantamp_db"
    MOTHERDUCK_TOKEN: Optional[str] = None

    # ------------------------------------------------------------------
    # Segurança / JWT
    # ------------------------------------------------------------------
    # Chave que assina os tokens de login. NÃO é senha de usuário.
    # Gere com: python -c "import secrets; print(secrets.token_urlsafe(64))"
    # Se ficar vazia, a API gera uma chave aleatória a cada start
    # (bom para desenvolvimento, mas todo mundo é deslogado ao reiniciar).
    JWT_SECRET_KEY: Optional[str] = None
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Bloqueio contra força bruta
    MAX_FAILED_LOGINS: int = 5
    LOCKOUT_MINUTES: int = 15

    # ------------------------------------------------------------------
    # Recuperação de senha
    # ------------------------------------------------------------------
    RESET_TOKEN_EXPIRE_MINUTES: int = 30
    MAX_RESET_REQUESTS_PER_HOUR: int = 3
    # URL pública onde ficam as páginas /admin/* (usada no link do e-mail)
    ADMIN_BASE_URL: str = "http://localhost:8000"

    # SMTP para enviar o link de redefinição. Sem SMTP_HOST, o link é
    # apenas escrito no log do servidor (útil em desenvolvimento).
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM: Optional[str] = None
    SMTP_STARTTLS: bool = True

    # ------------------------------------------------------------------
    # CORS — origens do front-end (JSON no .env)
    # ex.: CORS_ORIGINS=["https://plantamp.seudominio.br"]
    # ------------------------------------------------------------------
    CORS_ORIGINS: List[str] = ["*"]

    # Tamanho máximo do CSV de importação (MB)
    MAX_CSV_MB: int = 20

    # ------------------------------------------------------------------
    # BLAST (rota pública /api/search/blast)
    # ------------------------------------------------------------------
    # Motor usado quando o pedido não escolhe um:
    #   auto           -> blastp se o BLAST+ estiver instalado, senão smith-waterman
    #   smith-waterman -> sempre o alinhamento em Python (Biopython)
    #   blastp         -> sempre o BLAST+ do NCBI (erro 503 se não estiver instalado)
    BLAST_DEFAULT_ENGINE: Literal["auto", "smith-waterman", "blastp"] = "auto"
    # Pasta com blastp/makeblastdb. Vazio = procurar no PATH.
    # Ex. Windows: C:/Program Files/NCBI/blast-2.16.0+/bin
    BLAST_BIN_DIR: Optional[str] = None
    # Onde a API guarda o banco BLAST gerado a partir da tabela peptides
    BLAST_DB_DIR: str = "data/blastdb"
    BLASTP_TIMEOUT_SECONDS: int = 60
    BLAST_MIN_QUERY_LENGTH: int = 3
    BLAST_MAX_QUERY_LENGTH: int = 2000
    # Quantos BLASTs rodam ao mesmo tempo; os demais esperam na fila
    BLAST_MAX_CONCURRENT: int = 2
    # Quanto tempo um pedido espera na fila antes de receber 503
    BLAST_QUEUE_TIMEOUT_SECONDS: int = 20

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()