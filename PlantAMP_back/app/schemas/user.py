from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import validate_password_strength


class UserCreate(BaseModel):
    email: EmailStr
    full_name: Optional[str] = Field(None, max_length=120)
    password: str
    groups: List[str] = Field(default_factory=list, description='Ex.: ["admin"] ou ["curator"]')

    @field_validator("password")
    @classmethod
    def _strong(cls, v: str) -> str:
        return validate_password_strength(v)


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, max_length=120)
    is_active: Optional[bool] = None
    groups: Optional[List[str]] = None


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: Optional[str] = None
    is_active: bool
    groups: List[str]
    is_locked: bool
    last_login_at: Optional[datetime] = None
    password_changed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class ResetLinkResponse(BaseModel):
    reset_link: str
    expires_in_minutes: int
    emailed: bool
    message: str
