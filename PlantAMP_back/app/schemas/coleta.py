from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ColetaRequest(BaseModel):
    modo: Literal["novos", "sincronizar", "csv"] = Field(
        "novos", description="novos: só insere sequências novas | sincronizar: também atualiza as desta fonte | "
                             "csv: só gera o CSV, sem gravar no banco")
    inicio: int = Field(1, ge=1, le=10_000_000, description="Primeiro id numérico (PlantPepDB e dbAMP)")
    limite: int = Field(0, ge=0, le=10_000_000, description="Coletar só N ids, para testar (0 = todos)")


class ExecucaoResponse(BaseModel):
    status: str                       # queued, in_progress, completed...
    conclusion: Optional[str] = None  # success, failure, cancelled...
    titulo: Optional[str] = None
    evento: Optional[str] = None      # workflow_dispatch, schedule
    criado_em: Optional[datetime] = None
    url: str


class FonteColetaResponse(BaseModel):
    fonte: str
    nome: str
    descricao: str
    ultima_execucao: Optional[ExecucaoResponse] = None
    erro: Optional[str] = None


class ColetasResponse(BaseModel):
    configurado: bool
    repositorio: Optional[str] = None
    actions_url: Optional[str] = None
    fontes: List[FonteColetaResponse]


class ColetaDisparadaResponse(BaseModel):
    message: str
    acompanhar: str