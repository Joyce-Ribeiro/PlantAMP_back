from pydantic import BaseModel, Field
from typing import Optional

class PeptideBase(BaseModel):
    name: str
    sequence: str = Field(..., description="A sequência do peptídeo (deve ser única)")
    organism: str
    activity: str
    validation: str
    uniprot: str = "Not found"
    pdb: str = "Not found"
    reference: str
    pubmed: str
    fonte: Optional[str] = None

class PeptideCreate(PeptideBase):
    pass

class PeptideUpdate(BaseModel):
    name: Optional[str] = None
    sequence: Optional[str] = None
    organism: Optional[str] = None
    activity: Optional[str] = None
    validation: Optional[str] = None
    uniprot: Optional[str] = None
    pdb: Optional[str] = None
    reference: Optional[str] = None
    pubmed: Optional[str] = None
    fonte: Optional[str] = None

class PeptideResponse(PeptideBase):
    id: int

    class Config:
        from_attributes = True
