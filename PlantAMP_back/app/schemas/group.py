from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class PermissionResponse(BaseModel):
    code: str
    description: Optional[str] = None


class GroupCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=40, pattern=r"^[a-z0-9_-]+$")
    description: Optional[str] = Field(None, max_length=200)
    permissions: List[str] = Field(default_factory=list)


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=40, pattern=r"^[a-z0-9_-]+$")
    description: Optional[str] = Field(None, max_length=200)


class GroupPermissionsUpdate(BaseModel):
    permissions: List[str]


class GroupResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_system: bool
    permissions: List[str]
    member_count: int


class AccessMatrixRow(BaseModel):
    group_id: int
    group: str
    is_system: bool
    permissions: Dict[str, bool]


class AccessMatrixResponse(BaseModel):
    """Linhas = grupos, colunas = permissões, célula = true/false."""
    permissions: List[PermissionResponse]
    rows: List[AccessMatrixRow]
