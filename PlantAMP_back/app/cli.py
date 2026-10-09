"""
Comandos de terminal para quem tem acesso ao SERVIDOR (último recurso).

    python -m app.cli create-admin --email voce@lab.br --name "Seu Nome"
    python -m app.cli reset-password --email voce@lab.br
    python -m app.cli reset-link --email voce@lab.br
    python -m app.cli unlock --email voce@lab.br
    python -m app.cli list-admins

A senha é sempre digitada no terminal (getpass) — nunca vai para o .env,
para o histórico do shell nem para o código.

Banco local (.duckdb): pare a API antes, porque o DuckDB só permite um
processo escrevendo no arquivo. Com MotherDuck, pode rodar com a API no ar.
"""
import argparse
import getpass
import sys

from app.core.permissions import ADMIN_GROUP
from app.core.security import validate_password_strength
from app.db.connection import get_db
from app.db.init_db import create_tables
from app.services import accounts


def _ask_password() -> str:
    while True:
        pw = getpass.getpass("Nova senha: ")
        try:
            validate_password_strength(pw)
        except ValueError as e:
            print(f"  ✗ {e}")
            continue
        if getpass.getpass("Repita a senha: ") != pw:
            print("  ✗ As senhas não conferem.")
            continue
        return pw


def _require_user(db, email: str) -> dict:
    user = accounts.get_user_by_email(db, email)
    if not user:
        sys.exit(f"Usuário {email} não encontrado.")
    return user


def cmd_create_admin(db, args):
    existing = accounts.get_user_by_email(db, args.email)
    if existing:
        # Promove um usuário existente a admin (sem trocar senha)
        groups = set(accounts.get_user_groups(db, existing["id"])) | {ADMIN_GROUP}
        with accounts.transaction(db):
            accounts.set_user_groups(db, existing["id"], groups)
            db.execute("UPDATE users SET is_active = TRUE WHERE id = ?", [existing["id"]])
            accounts.audit(db, "cli_promote_admin", existing["id"], detail="via terminal")
        print(f"✓ {existing['email']} agora está no grupo '{ADMIN_GROUP}'.")
        return
    pw = _ask_password()
    with accounts.transaction(db):
        uid = accounts.create_user(db, args.email, pw, args.name, [ADMIN_GROUP])
        accounts.audit(db, "cli_create_admin", uid, detail="via terminal")
    print(f"✓ Admin criado: {accounts.normalize_email(args.email)} (id {uid}). Faça login em /admin/login")


def cmd_reset_password(db, args):
    user = _require_user(db, args.email)
    pw = _ask_password()
    with accounts.transaction(db):
        accounts.set_password(db, user["id"], pw)
        db.execute("UPDATE users SET is_active = TRUE WHERE id = ?", [user["id"]])
        accounts.audit(db, "cli_reset_password", user["id"], detail="via terminal")
    print(f"✓ Senha de {user['email']} redefinida, conta desbloqueada e sessões antigas encerradas.")


def cmd_reset_link(db, args):
    user = _require_user(db, args.email)
    token = accounts.create_reset_token(db, user["id"])
    accounts.audit(db, "cli_reset_link", user["id"], detail="via terminal")
    print("Link de uso único (abra no navegador):")
    print(accounts.build_reset_link(token))


def cmd_unlock(db, args):
    user = _require_user(db, args.email)
    db.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = ?", [user["id"]])
    accounts.audit(db, "cli_unlock", user["id"], detail="via terminal")
    print(f"✓ {user['email']} desbloqueado.")


def cmd_list_admins(db, args):
    rows = db.execute(
        """SELECT u.id, u.email, u.full_name, u.is_active, u.last_login_at
           FROM users u JOIN user_groups ug ON ug.user_id = u.id
           JOIN groups g ON g.id = ug.group_id WHERE g.name = ? ORDER BY u.id""",
        [ADMIN_GROUP],
    ).fetchall()
    if not rows:
        print("Nenhum admin cadastrado. Crie com: python -m app.cli create-admin --email ...")
    for uid, email, name, active, last in rows:
        print(f"[{uid}] {email}  {name or ''}  {'ativo' if active else 'INATIVO'}  último login: {last or '-'}")


def main():
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Administração do PlantAMP pelo terminal")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-admin", help="Criar admin (ou promover usuário existente)")
    p.add_argument("--email", required=True)
    p.add_argument("--name", default=None)
    p.set_defaults(func=cmd_create_admin)

    for name, func, help_ in [
        ("reset-password", cmd_reset_password, "Definir nova senha direto no terminal"),
        ("reset-link", cmd_reset_link, "Gerar link de redefinição de senha"),
        ("unlock", cmd_unlock, "Desbloquear conta após muitas tentativas"),
    ]:
        p = sub.add_parser(name, help=help_)
        p.add_argument("--email", required=True)
        p.set_defaults(func=func)

    sub.add_parser("list-admins", help="Listar admins").set_defaults(func=cmd_list_admins)

    args = parser.parse_args()
    create_tables()
    db = get_db()
    try:
        args.func(db, args)
    except ValueError as e:
        sys.exit(f"✗ {e}")


if __name__ == "__main__":
    main()
