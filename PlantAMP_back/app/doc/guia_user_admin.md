# Guia de administração — PlantAMP

Para quem vai **instalar, rodar ou administrar** o backend do PlantAMP.
Visitantes só consultam os dados e não precisam de nada disto (veja o [README](../README.md)).

**Sumário**
1. [Visão geral](#1-visão-geral)
2. [Requisitos](#2-requisitos)
3. [Instalação](#3-instalação)
4. [Configuração (.env)](#4-configuração-env)
5. [Criar o primeiro admin](#5-criar-o-primeiro-admin)
6. [Rodar a API](#6-rodar-a-api)
7. [Usando o painel /admin](#7-usando-o-painel-admin)
8. [Usuários, grupos e a matriz de acesso](#8-usuários-grupos-e-a-matriz-de-acesso)
9. [Esqueci a senha](#9-esqueci-a-senha)
10. [Importar peptídeos e trocar de conta do MotherDuck](#10-importar-peptídeos-e-trocar-de-conta-do-motherduck)
11. [Comandos de terminal](#11-comandos-de-terminal)
12. [Colocando em produção](#12-colocando-em-produção)
13. [Problemas comuns](#13-problemas-comuns)
14. [Estrutura do código](#14-estrutura-do-código)

---

## 1. Visão geral

| Ação | Quem pode |
|---|---|
| Consultar peptídeos (`GET`) | **Qualquer pessoa**, sem login |
| Cadastrar (`POST`) | quem tem `peptides:create` |
| Editar (`PUT` / `PATCH`) | quem tem `peptides:update` |
| Excluir (`DELETE`) | quem tem `peptides:delete` |
| Importar CSV | quem tem `peptides:import` |
| Gerenciar usuários | `users:read` / `users:manage` |
| Gerenciar a matriz de acesso | `groups:read` / `groups:manage` |

Não existe usuário admin no `.env`. Usuários, grupos e permissões ficam **no banco**.

---

## 2. Requisitos

- **Python 3.11, 3.12 ou 3.13.** O 3.14 ainda não funciona com o pandas usado aqui.
- Uma conta no **MotherDuck** com o token de acesso (ou um arquivo `.duckdb` local, para testes).
- Git, para baixar o projeto.

---

## 3. Instalação

Dentro da pasta do projeto:

```bash
# 1) criar o ambiente virtual (só na primeira vez)
python -m venv .venv

# 2) ativar o ambiente (sempre que abrir um terminal novo)
.venv\Scripts\activate            # Windows (PowerShell ou CMD)
source .venv/bin/activate         # Mac / Linux

# 3) instalar as dependências
pip install -r requirements.txt
```

Quando o ambiente está ativo, o terminal mostra `(.venv)` no começo da linha.

> **PowerShell bloqueou o `activate`?** Rode uma vez
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` e tente de novo.

---

## 4. Configuração (.env)

Copie o modelo e edite:

```bash
copy .env.example .env      # Windows
cp .env.example .env        # Mac / Linux
```

Campos principais:

| Variável | O que colocar |
|---|---|
| `MOTHERDUCK_TOKEN` | Token da conta do MotherDuck (*Settings → Access Tokens*) |
| `DATABASE_FILE` | `md:plantamp_db` (MotherDuck) ou `data/plantamp.duckdb` (local) |
| `JWT_SECRET_KEY` | Chave aleatória gerada com `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `ADMIN_BASE_URL` | Endereço onde a API roda, usado no link de "esqueci a senha". Local: `http://localhost:8000` |
| `SMTP_*` | Opcional. Servidor de e-mail para enviar o link de redefinição |
| `CORS_ORIGINS` | Domínio do site público, em JSON: `["https://plantamp.seudominio.br"]` |

**Primeira vez no MotherDuck?** Crie o banco no editor SQL do site:
`CREATE DATABASE plantamp_db;`
As tabelas são criadas sozinhas quando a API sobe; não existe comando de migração.

> O `.env` tem segredos. Ele já está no `.gitignore`. **Nunca** envie para o GitHub.

---

## 5. Criar o primeiro admin

```bash
python -m app.cli create-admin --email seu@email.com --name "Seu Nome"
```

- A senha é pedida duas vezes e **não aparece enquanto você digita** (isso é normal).
- A senha precisa ter no mínimo 10 caracteres, com letras e números.
- Rode num terminal comum. O console "Run" de algumas IDEs (como o PyCharm) não aceita a digitação escondida.
- Usando um banco **local** (`.duckdb`)? Pare a API antes, porque o arquivo só aceita um programa escrevendo por vez. Com MotherDuck não há esse problema.

Os próximos admins podem ser criados pelo painel; o terminal só é necessário para o primeiro.

---

## 6. Rodar a API

```bash
uvicorn app.main:app --reload
```

| Endereço | Para quê |
|---|---|
| http://localhost:8000/docs | Documentação interativa: ver e testar todos os endpoints |
| http://localhost:8000/admin/login | Login da área administrativa |
| http://localhost:8000/admin | Painel (depois do login) |
| http://localhost:8000/api/peptides/ | Consulta pública |

**Testar rotas protegidas no `/docs`:** clique em **Authorize** (cadeado), preencha
*username* com o seu **e-mail** e *password* com a sua senha. Deixe *client_id* e
*client_secret* em branco. O login vale por 60 minutos.

`--reload` reinicia a API quando o código muda. Use só em desenvolvimento.

---

## 7. Usando o painel /admin

Depois do login, o painel mostra só o que você tem permissão para ver.

- **Minha conta:** seus grupos e permissões, trocar senha e gerar códigos de recuperação.
- **Matriz de acesso:** marque e desmarque as permissões de cada grupo e clique em *Salvar alterações*. A mudança vale na hora para todos, sem precisar entrar de novo.
- **Usuários:** criar usuário, mudar grupos, gerar link de senha, desbloquear, desativar ou excluir.

> **Faça isto logo no primeiro acesso:** em *Minha conta → Códigos de recuperação*, gere os
> códigos e guarde-os fora do computador (impressos ou num gerenciador de senhas). Eles são
> o que salva sua conta se você esquecer a senha e não tiver e-mail configurado.

---

## 8. Usuários, grupos e a matriz de acesso

- As **permissões** são as ações (ex.: `peptides:import`).
- Os **grupos** recebem permissões. A tabela grupo × permissão é a *matriz de acesso*.
- Os **usuários** entram em um ou mais grupos e somam as permissões de todos eles.

Grupos que já vêm prontos:

| Grupo | Permissões | Observação |
|---|---|---|
| `admin` | todas | Grupo de sistema: não pode ser editado nem excluído |
| `curator` | cadastrar, editar, importar | Exemplo; pode alterar ou excluir |

**Regras de segurança automáticas**
- O sistema nunca fica sem pelo menos **um admin ativo**: a API bloqueia a ação que causaria isso.
- Ninguém concede uma permissão que não possui.
- Só um admin mexe no grupo `admin` ou na conta de outro admin.
- Ninguém desativa ou exclui a própria conta.
- Após 5 senhas erradas, a conta fica bloqueada por 15 minutos.

**Para novos membros da equipe:** crie o usuário com uma senha provisória, depois clique em
*Link de senha* e mande o link para a pessoa definir a própria senha.

---

## 9. Esqueci a senha

Use a primeira opção que der certo:

| # | Caminho | Onde | Precisa de |
|---|---|---|---|
| 1 | Link por e-mail | `/admin/forgot-password` | SMTP configurado no `.env` |
| 2 | Código de recuperação | `/admin/recovery` | Um dos códigos guardados |
| 3 | Outro admin ajuda | Painel → Usuários → *Link de senha* | Outro admin ativo |
| 4 | Terminal do servidor | `python -m app.cli reset-password --email ...` | Acesso à máquina e ao `.env` |

- O link vale 30 minutos e funciona uma única vez.
- Cada código de recuperação funciona uma única vez.
- Toda troca de senha **encerra as sessões abertas** da conta.
- Sem SMTP configurado, o link do caminho 1 aparece apenas no log do terminal onde a API está rodando.

---

## 10. Importar peptídeos e trocar de conta do MotherDuck

### Importar um CSV
No `/docs`, já logado, use `POST /api/peptides/import` e envie o arquivo.
Colunas obrigatórias: `name, sequence, organism, activity, validation, reference, pubmed`.
Opcionais: `uniprot`, `pdb` (se vierem vazias, viram `Not found`) e `fonte`.
Limite padrão: 20 MB (`MAX_CSV_MB`).

> A importação é tudo ou nada: se **uma** sequência do CSV já existir no banco, nenhuma
> linha é inserida.

### Trocar de conta do MotherDuck
1. Crie o banco na conta nova: `CREATE DATABASE plantamp_db;`
2. Coloque o token novo em `MOTHERDUCK_TOKEN` no `.env`.
3. Suba a API (as tabelas são criadas) e crie o admin (seção 5).
4. Exporte os dados da conta antiga (o script pede o token **antigo**):
   ```bash
   python scripts/exportar_peptideos.py --origem md:plantamp_db
   ```
5. Importe o `peptideos_exportados.csv` gerado, como explicado acima.

---

## 11. Comandos de terminal

Para quem tem acesso ao servidor. Rode com o ambiente virtual ativado.

```bash
python -m app.cli create-admin   --email x@y.com --name "Nome"   # cria admin (ou promove usuário existente)
python -m app.cli reset-password --email x@y.com                 # define nova senha direto
python -m app.cli reset-link     --email x@y.com                 # gera link de redefinição
python -m app.cli unlock         --email x@y.com                 # desbloqueia após 5 erros
python -m app.cli list-admins                                    # lista os admins
```

---

## 12. Colocando em produção

- [ ] `JWT_SECRET_KEY` fixa e secreta. Se ficar vazia, todo mundo é deslogado a cada reinício.
- [ ] `CORS_ORIGINS` só com o domínio do site público, sem `"*"`.
- [ ] `ADMIN_BASE_URL` com o endereço público real (`https://...`).
- [ ] SMTP configurado, para o "esqueci a senha" funcionar sozinho.
- [ ] Servir **somente via HTTPS**.
- [ ] Rodar sem `--reload`: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- [ ] Pelo menos **dois admins** ativos, cada um com códigos de recuperação guardados.

---

## 13. Problemas comuns

| Sintoma | Causa e solução |
|---|---|
| `pip install` falha no pandas | Python 3.14. Use 3.11–3.13. |
| Erro de versão ao conectar no MotherDuck | O MotherDuck exige DuckDB ≥ 1.4. Rode `pip install -r requirements.txt` de novo. |
| `Catalog Error` / banco não encontrado | Crie o banco na conta: `CREATE DATABASE plantamp_db;` |
| `IO Error: Could not set lock on file` | Banco local aberto por dois programas. Pare a API antes de usar o `app.cli`. |
| O terminal não aceita digitar a senha | Você está no console de uma IDE. Use o terminal do sistema. |
| Todos são deslogados ao reiniciar a API | `JWT_SECRET_KEY` vazia no `.env`. |
| `401` nas rotas protegidas | Não está logado, o token expirou (60 min) ou a senha foi trocada. Faça login de novo. |
| `403` | Logado, mas seu grupo não tem aquela permissão. Ajuste na matriz. |
| `429` no login | Conta bloqueada por 15 min após 5 erros. Espere ou use `app.cli unlock`. |
| `ModuleNotFoundError: app` | Rode os comandos de dentro da pasta do projeto, com o ambiente ativado. |

---

## 14. Estrutura do código

```
├── app/
│   ├── main.py                 inicia a API, rotas, cabeçalhos de segurança
│   ├── cli.py                  comandos de terminal (seção 11)
│   ├── core/
│   │   ├── config.py           leitura do .env
│   │   ├── security.py         hash de senha, tokens
│   │   ├── permissions.py      catálogo de permissões e grupos padrão
│   │   └── email.py            envio do link de senha
│   ├── db/                     conexão e criação das tabelas
│   ├── services/accounts.py    regras de contas e da matriz
│   ├── schemas/                formatos de entrada e saída da API
│   ├── api/
│   │   ├── dependencies.py     login obrigatório e checagem de permissão
│   │   └── routers/            peptides, auth, users, groups, páginas admin
│   └── static/admin/           páginas de login, recuperação e painel
├── scripts/exportar_peptideos.py
├── docs/GUIA_ADMIN.md          este guia
├── requirements.txt
├── .env.example
└── README.md                   apresentação pública
```

### Criar uma permissão nova
1. Acrescente o código em `app/core/permissions.py` (`PERMISSIONS`).
2. Proteja a rota com `Depends(require_permission("codigo:novo"))`.
3. Reinicie a API. A permissão é cadastrada, o grupo `admin` a recebe e ela aparece na matriz.

### Auditoria
Logins, falhas, redefinições de senha, importações, exclusões e mudanças na matriz ficam na
tabela `audit_log`. Para consultar no MotherDuck:
`SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 100;`