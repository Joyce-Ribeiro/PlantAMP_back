from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.peptide import PeptideResponse


# ----------------------------------------------------------------------
# Autocomplete
# ----------------------------------------------------------------------
class SuggestField(BaseModel):
    field: str
    label: str


class Suggestion(BaseModel):
    value: str
    count: int = Field(..., description="Quantos peptídeos têm este valor")


class SuggestResponse(BaseModel):
    field: str
    label: str
    query: str
    items: List[Suggestion]


class SuggestAllResponse(BaseModel):
    query: str
    groups: List[SuggestResponse]


# ----------------------------------------------------------------------
# Busca por atributos (paginada)
# ----------------------------------------------------------------------
class PeptideSearchItem(PeptideResponse):
    length: int


class PeptideSearchResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[PeptideSearchItem]


# ----------------------------------------------------------------------
# BLAST (alinhamento local)
# ----------------------------------------------------------------------
class BlastRequest(BaseModel):
    sequence: str = Field(
        ..., min_length=1, max_length=20000,
        description="Sequência de aminoácidos. Aceita texto puro ou FASTA (linha com '>').",
        examples=["GLFDIVKKVVGALGSL"],
    )
    max_hits: int = Field(50, ge=1, le=500)
    max_evalue: float = Field(10.0, gt=0, description="Descarta hits com E-value maior que isto")
    min_identity: float = Field(0.0, ge=0, le=100, description="Identidade mínima (%)")
    min_query_coverage: float = Field(0.0, ge=0, le=100, description="Cobertura mínima da query (%)")
    engine: Optional[Literal["auto", "smith-waterman", "blastp"]] = Field(
        None,
        description="auto = blastp se instalado, senão smith-waterman. Vazio = padrão do servidor "
                    "(BLAST_DEFAULT_ENGINE). Veja GET /api/search/blast/engines.",
    )


class BlastPeptide(BaseModel):
    id: int
    name: str
    organism: str
    activity: str
    validation: str
    uniprot: Optional[str] = None
    pdb: Optional[str] = None
    fonte: Optional[str] = None


class BlastHit(BaseModel):
    peptide: BlastPeptide
    score: float = Field(..., description="Score bruto (BLOSUM62, gap 11/1)")
    bit_score: float
    evalue: float
    identity: float = Field(..., description="% de posições idênticas no alinhamento")
    positives: float = Field(..., description="% de posições com score positivo")
    gaps: int
    alignment_length: int
    query_start: int = Field(..., description="1-based, inclusivo")
    query_end: int
    subject_start: int
    subject_end: int
    subject_length: int
    query_coverage: float = Field(..., description="% da query coberta pelo alinhamento")
    query_aligned: str
    midline: str = Field(..., description="Letra = idêntico, '+' = similar, espaço = diferente/gap")
    subject_aligned: str


class BlastEngine(BaseModel):
    name: str
    available: bool
    version: Optional[str] = None
    description: str
    detail: Optional[str] = Field(None, description="Por que não está disponível, se for o caso")


class BlastEnginesResponse(BaseModel):
    default: str = Field(..., description="Valor de BLAST_DEFAULT_ENGINE")
    resolved_default: str = Field(..., description="Motor que roda quando o pedido não escolhe nenhum")
    engines: List[BlastEngine]


class BlastResponse(BaseModel):
    query: str
    query_length: int
    engine: str = Field(..., description="Motor que realmente rodou: smith-waterman ou blastp")
    engine_version: Optional[str] = None
    matrix: str
    database_sequences: int
    database_residues: int
    hits: List[BlastHit]