from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Plantamp Backend"
    VERSION: str = "1.0.0"
    DATABASE_FILE: str = "data/plantamp.duckdb"

    class Config:
        env_file = ".env"

settings = Settings()