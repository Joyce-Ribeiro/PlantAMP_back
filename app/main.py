from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db.init_db import create_tables
from app.api.routers import peptides, users, groups

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="API robusta em DuckDB para a administração do banco Plantamp."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    create_tables()

app.include_router(peptides.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(groups.router, prefix="/api")

@app.get("/")
def root():
    return {"message": "Plantamp Backend em execução!"}