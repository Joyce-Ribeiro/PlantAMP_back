from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routers import admin_pages, auth, coletas, groups, peptides, users
from app.core.config import settings
from app.db.init_db import create_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=(
        "API robusta em DuckDB para a administração do banco Plantamp.\n\n"
        "**Leitura de peptídeos é pública.** Cadastro, edição, exclusão e importação "
        "de CSV exigem login e a permissão correspondente na matriz de acesso "
        "(use o botão *Authorize*)."
    ),
    lifespan=lifespan,
)

# O token vai no header Authorization (não usamos cookies), então
# allow_credentials=False. Em produção, defina CORS_ORIGINS no .env.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


ADMIN_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    if request.url.path.startswith("/admin"):
        response.headers["Content-Security-Policy"] = ADMIN_CSP
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
    if request.url.path.startswith(("/api/auth", "/api/users", "/api/coletas")):
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(auth.router, prefix="/api")
app.include_router(peptides.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(groups.router, prefix="/api")
app.include_router(coletas.router, prefix="/api")

# Área administrativa (páginas separadas do site público)
app.mount("/admin/assets", StaticFiles(directory=admin_pages.ADMIN_DIR / "assets"), name="admin-assets")
app.include_router(admin_pages.router)


@app.get("/")
def root():
    return {"message": "Plantamp Backend em execução!"}