"""
Funções de segurança: hash de senha (Argon2), tokens JWT, tokens de
redefinição de senha e códigos de recuperação.
"""
import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings

logger = logging.getLogger("plantamp.security")

# ----------------------------------------------------------------------
# Chave do JWT
# ----------------------------------------------------------------------
if settings.JWT_SECRET_KEY:
    SECRET_KEY = settings.JWT_SECRET_KEY
else:
    SECRET_KEY = secrets.token_urlsafe(64)
    logger.warning(
        "JWT_SECRET_KEY não definida no .env: usando chave temporária. "
        "Todos os logins serão invalidados quando a API reiniciar."
    )


def utcnow() -> datetime:
    """Data/hora atual em UTC, sem fuso (é como gravamos no DuckDB)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ----------------------------------------------------------------------
# Senhas (Argon2id)
# ----------------------------------------------------------------------
_ph = PasswordHasher()

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128


def validate_password_strength(password: str) -> str:
    """Regras mínimas de senha. Lança ValueError com mensagem em português."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"A senha precisa ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"A senha pode ter no máximo {MAX_PASSWORD_LENGTH} caracteres.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError("A senha precisa ter letras e números.")
    return password


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _ph.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# Usado quando o e-mail não existe: faz a mesma conta de um login real,
# para o tempo de resposta não revelar quais e-mails estão cadastrados.
_DUMMY_HASH = _ph.hash(secrets.token_urlsafe(16))


def dummy_password_check() -> None:
    verify_password("senha-invalida", _DUMMY_HASH)


# ----------------------------------------------------------------------
# JWT de acesso
# ----------------------------------------------------------------------
def create_access_token(user_id: int, token_version: int) -> str:
    """
    `ver` = token_version do usuário no banco. Ao trocar/redefinir a senha
    ou clicar em "sair de todos os dispositivos", a versão sobe e todos os
    tokens antigos deixam de valer na hora.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "ver": token_version,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "sub", "ver"]},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "access":
        return None
    try:
        payload["sub"] = int(payload["sub"])
    except (TypeError, ValueError):
        return None
    return payload


# ----------------------------------------------------------------------
# Tokens de redefinição (link por e-mail) e códigos de recuperação
# ----------------------------------------------------------------------
def generate_reset_token() -> str:
    """Token que vai no link. Só o hash SHA-256 é salvo no banco."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_recovery_code() -> str:
    """Código de uso único no formato XXXX-XXXX-XXXX-XXXX (64 bits)."""
    raw = secrets.token_hex(8).upper()
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def normalize_recovery_code(code: str) -> str:
    return re.sub(r"[^0-9A-Fa-f]", "", code).upper()
