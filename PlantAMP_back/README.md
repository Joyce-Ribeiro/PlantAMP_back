# PlantAMP — Backend

API FastAPI + DuckDB/MotherDuck do banco PlantAMP.

## Quem pode o quê

| Ação | Quem |
|---|---|
| `GET /api/peptides/`, `GET /api/peptides/{id}` | **Qualquer pessoa**, sem login |
| `POST /api/peptides/` | Quem tem `peptides:create` |
| `PUT/PATCH /api/peptides/{id}` | Quem tem `peptides:update` |
| `DELETE /api/peptides/{id}` | Quem tem `peptides:delete` |
| `POST /api/peptides/import` (CSV) | Quem tem `peptides:import` |
| `/api/users/*` | `users:read` / `users:manage` |
| `/api/groups/*` (matriz de acesso) | `groups:read` / `groups:manage` |

As permissões são dadas a **grupos**, e os usuários entram em grupos. Essa matriz
(grupo × permissão) fica **no banco**, não no `.env`, e pode ser editada no painel `/admin`.

- `admin`: grupo de sistema. Tem sempre todas as permissões, não pode ser editado nem excluído,
  e a API não deixa o sistema ficar sem nenhum admin ativo.
- `curator`: exemplo criado no primeiro start (cadastra, edita e importa, mas não exclui).
  Você pode alterá-lo ou excluí-lo.

Regras contra escalada de privilégio: ninguém concede uma permissão que não tem, e só um admin
mexe no grupo `admin` ou na conta de outro admin.

## Primeiro uso

```bash
pip install -r requirements.txt
cp .env.example .env          # preencha JWT_SECRET_KEY (e SMTP, se quiser e-mail)
python -m app.cli create-admin --email voce@lab.br --name "Seu Nome"   # pede a senha no terminal
uvicorn app.main:app --reload
```

Depois acesse **http://localhost:8000/admin/login**.

> Banco local (`.duckdb`): pare a API antes de rodar o `app.cli`, porque o DuckDB só aceita
> um processo escrevendo no arquivo. Com MotherDuck, o CLI pode rodar com a API no ar.

## Páginas administrativas (separadas do site público)

| URL | Para quê |
|---|---|
| `/admin/login` | Login |
| `/admin` | Painel: minha conta, códigos de recuperação, matriz de acesso, usuários |
| `/admin/forgot-password` | Pedir link de redefinição por e-mail |
| `/admin/reset-password#token=…` | Criar nova senha a partir do link |
| `/admin/recovery` | Redefinir senha com código de recuperação |

## Admin esqueceu a senha? Quatro caminhos, do mais simples ao último recurso

1. **Link por e-mail.** Em `/admin/forgot-password`, o link vale 30 min e só pode ser usado uma vez.
   Requer SMTP no `.env`; sem SMTP, o link aparece no log do servidor.
2. **Código de recuperação.** Em `/admin/recovery`. Os 10 códigos são gerados no painel e cada um
   vale uma vez. Funciona mesmo sem e-mail.
3. **Outro admin ajuda.** No painel, em *Usuários*, o botão *Link de senha* gera um link de uso único.
4. **Pelo terminal do servidor** (último recurso, para quem tem acesso à máquina):
   ```bash
   python -m app.cli reset-password --email voce@lab.br   # define nova senha direto
   python -m app.cli reset-link --email voce@lab.br       # ou gera um link
   python -m app.cli unlock --email voce@lab.br           # desbloqueia após 5 erros
   python -m app.cli list-admins
   ```

Toda redefinição de senha encerra as sessões abertas daquela conta.

## Proteções incluídas

- Senhas com Argon2id; nunca são salvas em texto nem vão para o `.env`.
- Token JWT de 60 min, assinado com `JWT_SECRET_KEY`. Trocar ou redefinir a senha, desativar o
  usuário ou usar "sair de todos" invalida os tokens antigos na hora.
- Permissões relidas do banco a cada requisição: mudar a matriz vale sem novo login.
- Bloqueio de 15 min após 5 senhas erradas. Mensagens de login e de "esqueci a senha" não
  revelam se um e-mail está cadastrado.
- Links e códigos de recuperação são guardados só como hash SHA-256 e são de uso único. O token
  vai depois do `#` no link, então não aparece em logs nem no cabeçalho Referer.
- Páginas `/admin` com CSP restrita, sem iframe e com `noindex`.
- Tabela `audit_log` com logins, falhas, redefinições, importações, exclusões e mudanças na matriz.
- Limite de tamanho do CSV (`MAX_CSV_MB`).

## Adicionar uma permissão nova

1. Inclua o código em `app/core/permissions.py` → `PERMISSIONS`.
2. Use na rota: `user: CurrentUser = Depends(require_permission("codigo:novo"))`.
3. Reinicie a API. A permissão é cadastrada no banco, o grupo `admin` a recebe automaticamente,
   e ela aparece como coluna nova na matriz do painel.

## Usar no front-end público (React/Vue etc.)

O site público só faz `GET`, sem token. Para chamadas autenticadas fora do `/admin`, envie
`Authorization: Bearer <access_token>` (o token vem de `POST /api/auth/login`).
Em produção, defina `CORS_ORIGINS` com o domínio do front-end.
