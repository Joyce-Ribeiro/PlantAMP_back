# Guia das coletas de dados — PlantAMP

As coletas que antes rodavam no notebook `limpeza_base.ipynb` (Colab) agora rodam
no **GitHub Actions**, de graça, e gravam direto no banco (MotherDuck).
Cada fonte tem o seu workflow e pode ser disparada pela aba *Actions* do GitHub,
pelo painel `/admin` ou pela API.

| Fonte | Workflow | Tempo da coleta completa |
|---|---|---|
| PlantPepDB | `coleta-plantpepdb.yml` | ~10 min |
| dbAMP | `coleta-dbamp.yml` | ~2h30 (o GitHub permite até 6h) |
| APD6 | `coleta-apd.yml` | ~5 min |

---

## 1. Onde fica cada arquivo

```
.                                   ← raiz do repositório no GitHub
├── .github/workflows/
│   ├── _coleta.yml                 etapas comuns (não roda sozinho)
│   ├── coleta-plantpepdb.yml
│   ├── coleta-dbamp.yml
│   └── coleta-apd.yml
└── PlantAMP_back/
    ├── coleta/                     os coletores (código que era o notebook)
    │   ├── __init__.py
    │   ├── __main__.py             comando: python -m coleta ...
    │   ├── comum.py                limpeza, HTTP com novas tentativas, paralelismo
    │   ├── banco.py                gravação no MotherDuck
    │   ├── plantpepdb.py
    │   ├── dbamp.py
    │   └── apd.py
    ├── requirements-coleta.txt     dependências só dos coletores
    └── app/ ...                    (API: ver seção 5)
```

> O GitHub só lê workflows da pasta `.github/workflows/` na **raiz do repositório**.
> Uma cópia dentro de `PlantAMP_back/` é ignorada. Como o código fica na subpasta,
> o `_coleta.yml` roda os comandos com `working-directory: PlantAMP_back`.

---

## 2. Configurar o GitHub (uma vez)

1. No repositório: **Settings → Secrets and variables → Actions → New repository secret**
   - Nome: `MOTHERDUCK_TOKEN`
   - Valor: um token do MotherDuck (*Settings → Access Tokens*). Recomendo criar um token
     só para as coletas, assim dá para revogá-lo sem derrubar a API.
2. (Opcional) Se o banco não se chama `plantsamp_db`, na aba **Variables** crie
   `DATABASE_FILE` com o valor `md:nome_do_banco`.
3. Faça commit e push dos arquivos para a branch **main**. O botão *Run workflow* só
   aparece quando o workflow já está na branch padrão.

---

## 3. Primeiro teste (sem gravar nada)

1. Abra a aba **Actions** do repositório e escolha **Coleta APD6** na lista da esquerda.
2. Clique em **Run workflow** e preencha: modo `csv`, limite `5`.
3. Quando terminar (1 a 2 min), abra a execução:
   - o **resumo** mostra quantos ids foram lidos e quantas falhas houve;
   - em **Artifacts** está o `apd.csv` para conferir.
4. Repita com **Coleta PlantPepDB** e **Coleta dbAMP** (limite `20`), para confirmar que os
   servidores dessas fontes respondem às máquinas do GitHub.

Se tudo estiver certo, rode cada uma com modo `novos` e limite `0` (tudo).

---

## 4. Os três modos

| Modo | O que faz |
|---|---|
| `novos` (padrão) | Insere só as sequências que ainda não estão no banco. Não altera nada que já existe. |
| `sincronizar` | Faz o mesmo e **atualiza** as linhas que vieram desta mesma fonte (coluna `fonte`). Nunca mexe em peptídeos cadastrados à mão ou de outra fonte. |
| `csv` | Só gera o CSV (fica em *Artifacts* por 30 dias). Não toca no banco. |

Outros campos:
- **inicio**: primeiro id a coletar (PlantPepDB e dbAMP). Ex.: `35000` no dbAMP pega só o
  final da lista, em poucos minutos, em vez de refazer tudo.
- **limite**: coleta só N ids, para testes. `0` = tudo.

Ids novos publicados pelas fontes entram sozinhos: depois do último id conhecido, o coletor
continua procurando até achar 50 ids seguidos vazios.

**Proteções**
- Se mais de 5% dos ids falharem (site instável), nada é gravado e a execução fica vermelha.
- A gravação é uma transação única: grava tudo ou nada.
- Cada gravação fica registrada na tabela `audit_log` (ação `coleta`).
- Duas coletas da mesma fonte nunca rodam juntas.

---

## 5. Disparar pelo painel /admin e pela API

### 5.1 Arquivos da API (substitua ou acrescente)

| Arquivo | O que mudou |
|---|---|
| `app/api/routers/coletas.py` | **novo**: `GET /api/coletas/` e `POST /api/coletas/{fonte}` |
| `app/schemas/coleta.py` | **novo**: formatos de entrada e saída |
| `app/core/config.py` | + `GITHUB_TOKEN`, `GITHUB_REPO`, `GITHUB_REF` |
| `app/core/permissions.py` | + permissão `coletas:run` |
| `app/main.py` | registra o router de coletas |
| `app/static/admin/panel.html` | + seção *Coletas de dados* |
| `app/static/admin/assets/panel.js` | + lógica da seção |
| `app/static/admin/assets/admin.css` | + estilo do seletor de modo e do status "em andamento" |

### 5.2 Criar o token do GitHub

1. GitHub → foto do perfil → **Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate new token**.
2. *Repository access*: **Only select repositories** → escolha só este repositório.
3. *Permissions → Repository permissions → Actions*: **Read and write**.
4. Defina uma validade (ex.: 1 ano) e copie o token.

### 5.3 Configurar o .env do servidor

```env
GITHUB_TOKEN=github_pat_xxxxxxxxxxxxxxxx
GITHUB_REPO=seu-usuario/PlantAMP_back
GITHUB_REF=main
```

Reinicie a API. O grupo `admin` recebe a permissão `coletas:run` automaticamente.
Para liberar a outro grupo (ex.: `curator`), marque `coletas:run` na **matriz de acesso**.

### 5.4 Usar

- **Painel**: `/admin` → seção **Coletas de dados** → escolha o modo → **Executar**.
  A tabela mostra a última execução de cada fonte e o link para os detalhes e o CSV.
- **API** (com o token de login do painel):
  ```bash
  curl -X POST https://SEU_SERVIDOR/api/coletas/dbamp \
       -H "Authorization: Bearer SEU_TOKEN_DE_LOGIN" \
       -H "Content-Type: application/json" \
       -d '{"modo": "novos", "inicio": 35000}'
  ```
  Resposta `202` = coleta enviada; `409` = já existe uma rodando; `502` = problema com o
  token ou o repositório do GitHub (a mensagem diz qual).

---

## 6. Coleta automática mensal (opcional)

Em cada `coleta-*.yml`, apague o `#` destas duas linhas:

```yaml
  # schedule:
  #   - cron: "17 6 1 * *"   # dia 1 de cada mês, 03:17 em Brasília
```

As três fontes já vêm em dias diferentes (1, 2 e 3). Agendadas, elas rodam no modo `novos`.

> Em repositório **público**, o GitHub desliga agendamentos depois de 60 dias sem nenhum
> commit. Os disparos manuais e pela API continuam funcionando.

---

## 7. Rodar no seu computador

```bash
pip install -r requirements-coleta.txt
python -m coleta --fonte apd --modo csv            # só gera saida/apd.csv
python -m coleta --fonte dbamp --modo novos --inicio 35000
python -m coleta --help
```

Usa as mesmas variáveis do `.env` da API (`MOTHERDUCK_TOKEN`, `DATABASE_FILE`), que
precisam estar exportadas no terminal. Acrescente `saida/` ao `.gitignore`.

---

## 8. Problemas comuns

| Sintoma | Causa e solução |
|---|---|
| Não aparece o botão *Run workflow* | O arquivo ainda não está na branch `main`. |
| "Nenhum registro coletado" | O site da fonte está fora do ar, bloqueou o GitHub ou mudou o layout. Teste abrindo o site; se mudou, o parser em `coleta/<fonte>.py` precisa de ajuste. |
| "X% dos ids falharam" | Site instável. Rode de novo mais tarde; nada foi gravado. |
| "MOTHERDUCK_TOKEN não definido" | Falta o secret do passo 2. |
| "A tabela 'peptides' não existe" | O `DATABASE_FILE` aponta para outro banco, ou a API nunca subiu nesse banco. |
| Painel: "Coletas não configuradas" | Falta `GITHUB_TOKEN`/`GITHUB_REPO` no `.env`, ou a API não foi reiniciada. |
| `502` com "não tem a permissão" | O token não tem *Actions: Read and write* neste repositório. |
| Execução do dbAMP cancelada por tempo | Passou de 5h40. Divida a coleta usando `inicio` e `limite`. |

---

## 9. Diferenças em relação ao notebook

- Cada fonte grava a coluna `fonte` (`PlantPepDB`, `dbAMP`, `APD6`).
- `pubmed` vazio virou sempre `Not available` (antes cada fonte usava uma grafia).
- O CSV sai em UTF-8 sem BOM. O do APD saía com BOM, o que quebrava a primeira coluna
  no `POST /api/peptides/import`.
- O PlantPepDB remove registros sem nome **antes** de eliminar sequências repetidas, então
  uma sequência repetida não se perde quando a primeira cópia não tinha nome.
- Atividades do APD saem em ordem alfabética (antes a ordem variava a cada execução).
- Falhas de rede têm até 4 novas tentativas antes de contar como falha.
- Não gera mais `.zip`.