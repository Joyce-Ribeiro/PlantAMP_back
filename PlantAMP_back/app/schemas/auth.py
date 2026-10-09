from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import validate_password_strength


class NewPasswordMixin(BaseModel):
    new_password: str = Field(..., description="Mínimo 10 caracteres, com letras e números")

    @field_validator("new_password")
    @classmethod
    def _strong(cls, v: str) -> str:
        return validate_password_strength(v)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=128)


class MeResponse(BaseModel):
    id: int
    email: str
    full_name: Optional[str] = None
    groups: List[str]
    permissions: List[str]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # segundos
    user: MeResponse


class ChangePasswordRequest(NewPasswordMixin):
    current_password: str = Field(..., max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(NewPasswordMixin):
    token: str = Field(..., min_length=20, max_length=200)


class RecoverWithCodeRequest(NewPasswordMixin):
    email: EmailStr
    recovery_code: str = Field(..., min_length=16, max_length=40)


class ConfirmPasswordRequest(BaseModel):
    current_password: str = Field(..., max_length=128)


class RecoveryCodesResponse(BaseModel):
    codes: List[str]
    message: str


class RecoveryCodesStatus(BaseModel):
    remaining: int


class MessageResponse(BaseModel):
    message: str
