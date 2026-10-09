import duckdb
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies import CurrentUser, client_ip, get_current_user, get_database
from app.core.config import settings
from app.core.email import send_password_reset_email
from app.core.security import (
    create_access_token,
    dummy_password_check,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.schemas.auth import (
    ChangePasswordRequest,
    ConfirmPasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    MessageResponse,
    RecoverWithCodeRequest,
    RecoveryCodesResponse,
    RecoveryCodesStatus,
    ResetPasswordRequest,
    TokenResponse,
)
from app.services import accounts

router = APIRouter(prefix="/auth", tags=["Auth"])

INVALID_LOGIN = "E-mail ou senha incorretos."
LOCKED = "Muitas tentativas. Aguarde alguns minutos ou redefina a senha."


def _me(db, user_id: int) -> MeResponse:
    user = accounts.get_user_by_id(db, user_id)
    return MeResponse(
        id=user["id"],
        email=user["email"],
        full_name=user["full_name"],
        groups=accounts.get_user_groups(db, user_id),
        permissions=sorted(accounts.get_user_permissions(db, user_id)),
    )


def _token_response(db, user_id: int) -> TokenResponse:
    user = accounts.get_user_by_id(db, user_id)
    return TokenResponse(
        access_token=create_access_token(user["id"], user["token_version"]),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=_me(db, user_id),
    )


def _authenticate(db, email: str, password: str, ip: str | None) -> TokenResponse:
    user = accounts.get_user_by_email(db, email)

    if user is None:
        dummy_password_check()  # mesmo tempo de resposta de um usuário real
        accounts.audit(db, "login_failed", detail=f"email desconhecido: {accounts.normalize_email(email)}", ip=ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID_LOGIN)

    if accounts.is_locked(user):
        accounts.audit(db, "login_blocked", user["id"], ip=ip)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, LOCKED)

    if not verify_password(password, user["password_hash"]):
        accounts.register_failed_attempt(db, user)
        accounts.audit(db, "login_failed", user["id"], ip=ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID_LOGIN)

    if not user["is_active"]:
        accounts.audit(db, "login_inactive", user["id"], ip=ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID_LOGIN)

    if password_needs_rehash(user["password_hash"]):
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", [hash_password(password), user["id"]])

    accounts.register_successful_login(db, user["id"])
    accounts.audit(db, "login", user["id"], ip=ip)
    return _token_response(db, user["id"])


# ----------------------------------------------------------------------
# Login
# ----------------------------------------------------------------------
@router.post("/login", response_model=TokenResponse, summary="Login (JSON) — usado pela página /admin/login")
def login(body: LoginRequest, request: Request, db: duckdb.DuckDBPyConnection = Depends(get_database)):
    return _authenticate(db, body.email, body.password, client_ip(request))


@router.post("/token", response_model=TokenResponse, include_in_schema=False)
def login_form(request: Request, form: OAuth2PasswordRequestForm = Depends(),
               db: duckdb.DuckDBPyConnection = Depends(get_database)):
    """Mesmo login em formato de formulário — usado pelo botão 'Authorize' do /docs."""
    return _authenticate(db, form.username, form.password, client_ip(request))


@router.get("/me", response_model=MeResponse, summary="Quem sou eu e o que posso fazer")
def me(user: CurrentUser = Depends(get_current_user)):
    return MeResponse(id=user.id, email=user.email, full_name=user.full_name,
                      groups=user.groups, permissions=sorted(user.permissions))


@router.post("/logout-all", response_model=MessageResponse, summary="Encerrar todas as minhas sessões")
def logout_all(request: Request, user: CurrentUser = Depends(get_current_user),
               db: duckdb.DuckDBPyConnection = Depends(get_database)):
    accounts.bump_token_version(db, user.id)
    accounts.audit(db, "logout_all", user.id, ip=client_ip(request))
    return {"message": "Todas as sessões foram encerradas."}


@router.post("/change-password", response_model=TokenResponse, summary="Trocar a própria senha")
def change_password(body: ChangePasswordRequest, request: Request,
                    user: CurrentUser = Depends(get_current_user),
                    db: duckdb.DuckDBPyConnection = Depends(get_database)):
    row = accounts.get_user_by_id(db, user.id)
    if not verify_password(body.current_password, row["password_hash"]):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Senha atual incorreta.")
    accounts.set_password(db, user.id, body.new_password)
    accounts.audit(db, "password_changed", user.id, ip=client_ip(request))
    # As outras sessões caem; esta recebe um token novo.
    return _token_response(db, user.id)


# ----------------------------------------------------------------------
# Recuperação 1: "Esqueci minha senha" -> link por e-mail
# ----------------------------------------------------------------------
@router.post("/forgot-password", response_model=MessageResponse, status_code=202,
             summary="Pedir link de redefinição por e-mail")
def forgot_password(body: ForgotPasswordRequest, request: Request, background: BackgroundTasks,
                    db: duckdb.DuckDBPyConnection = Depends(get_database)):
    generic = {"message": "Se este e-mail estiver cadastrado, você receberá um link para redefinir a senha."}
    user = accounts.get_user_by_email(db, body.email)

    # Resposta é sempre a mesma: não revela se o e-mail existe.
    if not user or not user["is_active"]:
        return generic
    if accounts.recent_reset_requests(db, user["id"]) >= settings.MAX_RESET_REQUESTS_PER_HOUR:
        accounts.audit(db, "reset_rate_limited", user["id"], ip=client_ip(request))
        return generic

    token = accounts.create_reset_token(db, user["id"])
    background.add_task(send_password_reset_email, user["email"], accounts.build_reset_link(token))
    accounts.audit(db, "reset_requested", user["id"], ip=client_ip(request))
    return generic


@router.post("/reset-password", response_model=MessageResponse, summary="Criar nova senha usando o link")
def reset_password(body: ResetPasswordRequest, request: Request,
                   db: duckdb.DuckDBPyConnection = Depends(get_database)):
    with accounts.transaction(db):
        user_id = accounts.consume_reset_token(db, body.token)
        if user_id is not None:
            accounts.set_password(db, user_id, body.new_password)
            accounts.audit(db, "password_reset_link", user_id, ip=client_ip(request))
    if user_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Link inválido, expirado ou já utilizado.")
    return {"message": "Senha redefinida. Faça login com a nova senha."}


# ----------------------------------------------------------------------
# Recuperação 2: códigos de recuperação (funciona sem e-mail)
# ----------------------------------------------------------------------
@router.post("/recover", response_model=MessageResponse, summary="Redefinir senha com código de recuperação")
def recover_with_code(body: RecoverWithCodeRequest, request: Request,
                      db: duckdb.DuckDBPyConnection = Depends(get_database)):
    invalid = HTTPException(status.HTTP_400_BAD_REQUEST, "E-mail ou código de recuperação inválido.")
    ip = client_ip(request)
    user = accounts.get_user_by_email(db, body.email)

    if not user or not user["is_active"]:
        accounts.audit(db, "recover_failed", detail=f"email: {accounts.normalize_email(body.email)}", ip=ip)
        raise invalid
    if accounts.is_locked(user):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, LOCKED)

    with accounts.transaction(db):
        ok = accounts.consume_recovery_code(db, user["id"], body.recovery_code)
        if ok:
            accounts.set_password(db, user["id"], body.new_password)
            accounts.audit(db, "password_reset_code", user["id"], ip=ip)

    if not ok:
        accounts.register_failed_attempt(db, user)  # conta para o bloqueio
        accounts.audit(db, "recover_failed", user["id"], ip=ip)
        raise invalid

    left = accounts.remaining_recovery_codes(db, user["id"])
    return {"message": f"Senha redefinida. Restam {left} código(s) de recuperação."
                       + (" Gere novos códigos no painel." if left <= 3 else "")}


@router.get("/recovery-codes", response_model=RecoveryCodesStatus, summary="Quantos códigos me restam")
def recovery_codes_status(user: CurrentUser = Depends(get_current_user),
                          db: duckdb.DuckDBPyConnection = Depends(get_database)):
    return {"remaining": accounts.remaining_recovery_codes(db, user.id)}


@router.post("/recovery-codes", response_model=RecoveryCodesResponse,
             summary="Gerar novos códigos de recuperação (apaga os antigos)")
def generate_recovery_codes(body: ConfirmPasswordRequest, request: Request,
                            user: CurrentUser = Depends(get_current_user),
                            db: duckdb.DuckDBPyConnection = Depends(get_database)):
    row = accounts.get_user_by_id(db, user.id)
    if not verify_password(body.current_password, row["password_hash"]):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Senha atual incorreta.")
    with accounts.transaction(db):
        codes = accounts.generate_recovery_codes(db, user.id)
        accounts.audit(db, "recovery_codes_generated", user.id, ip=client_ip(request))
    return {
        "codes": codes,
        "message": "Guarde estes códigos fora do computador (impresso ou num gerenciador de senhas). "
                   "Cada um funciona uma única vez e eles não serão mostrados de novo.",
    }
