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

class PeptideResponse(PeptideBase):
    id: int

    class Config:
        from_attributes = True