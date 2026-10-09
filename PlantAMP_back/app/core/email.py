import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger("plantamp.email")


def send_email(to: str, subject: str, body: str) -> bool:
    """
    Envia e-mail em texto simples. Sem SMTP configurado, escreve a mensagem
    no log do servidor (só quem tem acesso ao servidor consegue ler).
    """
    if not settings.SMTP_HOST:
        logger.warning(
            "SMTP não configurado — e-mail NÃO enviado.\nPara: %s\nAssunto: %s\n\n%s",
            to, subject, body,
        )
        return False

    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        if settings.SMTP_PORT == 465:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT,
                                  context=ssl.create_default_context(), timeout=15) as s:
                if settings.SMTP_USER:
                    s.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
                s.send_message(msg)
        else:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as s:
                if settings.SMTP_STARTTLS:
                    s.starttls(context=ssl.create_default_context())
                if settings.SMTP_USER:
                    s.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
                s.send_message(msg)
        return True
    except Exception:  # noqa: BLE001 — falha de e-mail não pode derrubar a API
        logger.exception("Falha ao enviar e-mail para %s", to)
        return False


def send_password_reset_email(to: str, link: str) -> bool:
    body = (
        "Olá,\n\n"
        "Recebemos um pedido para redefinir a senha da sua conta de administração do PlantAMP.\n\n"
        f"Para criar uma nova senha, acesse o link abaixo (válido por "
        f"{settings.RESET_TOKEN_EXPIRE_MINUTES} minutos, uso único):\n\n"
        f"{link}\n\n"
        "Se você não pediu isso, ignore este e-mail — sua senha atual continua valendo.\n"
    )
    return send_email(to, "PlantAMP — redefinição de senha", body)
