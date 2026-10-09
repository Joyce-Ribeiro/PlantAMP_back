# PlantAMP

Banco de dados de **peptídeos antimicrobianos de plantas**. Reúne sequências de fontes públicas
(PlantPepDB, dbAMP e APD6), limpa e remove duplicatas, e as disponibiliza por uma API.

- **API pública** de consulta, sem login (`GET /api/peptides/`).
- **Painel administrativo** (`/admin`) para cadastrar, editar e importar peptídeos, e para
  gerenciar usuários, grupos e permissões.
- **Coletas automáticas** no GitHub Actions, que podem ser disparadas pelo painel e gravam
  direto no banco.

Tecnologias: Python 3.12, FastAPI, DuckDB / MotherDuck e GitHub Actions.

---

## Estrutura do repositório

```
.
├── .github/workflows/          coletas no GitHub Actions
│   ├── _coleta.yml             etapas comuns (reutilizável, não roda sozinho)
│   ├── coleta-plantpepdb.yml
│   ├── coleta-dbamp.yml
│   └── coleta-apd.yml
├── PlantAMP_back/              backend
│   ├── app/                    API FastAPI + painel /admin
│   │   ├── api/routers/        rotas: auth, peptides, users, groups, coletas, admin_pages
│   │   ├── core/               configuração, segurança, permissões, e-mail
│   │   ├── db/                 conexão e criação das tabelas
│   │   ├── schemas/            modelos Pydantic
│   │   ├── services/           regras de contas e auditoria
│   │   ├── static/admin/       páginas do painel
│   │   ├── doc/                guias detalhados
│   │   └── cli.py              comandos de terminal (criar admin, redefinir senha...)
│   ├── coleta/                 coletores (python -m coleta)
│   ├── requirements.txt        dependências da API
│   ├── requirements-coleta.txt dependências só dos coletores
│   └── .env.example            modelo de configuração
└── limpeza_base.ipynb          notebook original das coletas (histórico)
```

---

## Como rodar a API localmente

```bash
cd PlantAMP_back
pip install -r requirements.txt
cp .env.example .env
python -m app.cli create-admin --email voce@lab.br --name "Seu Nome"
uvicorn app.main:app --reload
```

Antes de criar o admin, preencha no `.env` pelo menos `JWT_SECRET_KEY` e o banco
(`MOTHERDUCK_TOKEN` + `DATABASE_FILE`). Para gerar a chave:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Para testar sem MotherDuck, use um banco local: `DATABASE_FILE=data/plantamp.duckdb`.

Depois de subir a API:

| Endereço | O que é |
|---|---|
| http://localhost:8000/docs | Documentação interativa da API (Swagger) |
| http://localhost:8000/admin/login | Painel administrativo |
| http://localhost:8000/api/peptides/ | Consulta pública de peptídeos |

---

## Coletas de dados

Cada fonte tem um workflow próprio no GitHub Actions:

| Fonte | Workflow | Coleta completa |
|---|---|---|
| PlantPepDB | `coleta-plantpepdb.yml` | ~10 min |
| dbAMP | `coleta-dbamp.yml` | ~2h30 |
| APD6 | `coleta-apd.yml` | ~5 min |

**Modos:**
- `novos`: só insere sequências novas.
- `sincronizar`: também atualiza as que vieram da mesma fonte.
- `csv`: só gera o CSV, sem gravar no banco.

O CSV de cada execução fica em *Artifacts* por 30 dias.

**Como disparar:**
- pela aba **Actions** do GitHub (*Run workflow*);
- pelo painel `/admin`, na seção *Coletas de dados*;
- pela API: `POST /api/coletas/{fonte}`, com a permissão `coletas:run`.

**Configuração necessária:**

| Onde | Variável | Para quê |
|---|---|---|
| GitHub → Settings → Secrets and variables → Actions → *Secrets* | `MOTHERDUCK_TOKEN` | As coletas gravarem no banco |
| GitHub → … → *Variables* (opcional) | `DATABASE_FILE` | Só se o banco não for `md:plantsamp_db` |
| `.env` da API | `GITHUB_TOKEN` | Token fine-grained com *Actions: Read and write* neste repositório |
| `.env` da API | `GITHUB_REPO` | No formato `usuario/repositorio`, **sem** `https://github.com/` |
| `.env` da API | `GITHUB_REF` | Branch dos workflows (`main`) |

Para rodar uma coleta no próprio computador:

```bash
cd PlantAMP_back
pip install -r requirements-coleta.txt
python -m coleta --fonte apd --modo csv --limite 5
```

---

## Documentação

- [PlantAMP_back/README.md](PlantAMP_back/README.md): permissões, painel, recuperação de senha
  e proteções de segurança.
- [Guia de usuários e administração](PlantAMP_back/app/doc/guia_user_admin.md)
- [Guia das coletas](PlantAMP_back/app/doc/guia_coletas.md)

---

## Problemas comuns

| Mensagem | Causa provável |
|---|---|
| Painel: "Workflow não encontrado" | `GITHUB_REPO` com URL completa em vez de `usuario/repositorio`, ou workflows fora da branch `GITHUB_REF`. |
| Painel: "Coletas não configuradas" | Falta `GITHUB_TOKEN`/`GITHUB_REPO` no `.env`, ou a API não foi reiniciada. |
| Actions: "Invalid MotherDuck token" | Secret `MOTHERDUCK_TOKEN` colado errado (com o nome, com aspas ou incompleto). |
| Actions: "no database/share named …" | Nome do banco diferente do que existe no MotherDuck. Confira `DATABASE_FILE`. |
| Correção não surtiu efeito no Actions | O *Re-run* repete o commit antigo. Dispare uma execução nova. |
