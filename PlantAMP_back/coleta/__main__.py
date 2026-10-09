"""
python -m coleta --fonte {plantpepdb,dbamp,apd} [--modo novos|sincronizar|csv]
                 [--inicio N] [--limite N] [--workers N] [--saida pasta] [--max-falhas 0.05]

Sempre salva o CSV tratado em <saida>/<fonte>.csv (no formato do
POST /api/peptides/import). Depois, conforme o --modo, grava no banco.
"""
import argparse
import importlib
import logging
import os
import sys
import time
from pathlib import Path

from coleta.banco import MODOS, conectar, gravar
from coleta.comum import log

FONTES = {"plantpepdb": "coleta.plantpepdb", "dbamp": "coleta.dbamp", "apd": "coleta.apd"}


def _resumo_markdown(fonte_nome, args, res, df, banco, segundos) -> str:
    linhas = [
        f"## Coleta {fonte_nome}",
        "",
        "| | |", "|---|---|",
        f"| Modo | `{args.modo}` |",
        f"| Ids consultados | {res.tentados} |",
        f"| Registros lidos | {len(res.registros)} |",
        f"| Falhas de rede | {len(res.falhas)} ({res.taxa_falha:.1%}) |",
        f"| Linhas no CSV (únicas) | {len(df)} |",
    ]
    if banco:
        linhas += [f"| Inseridos no banco | **{banco['inseridos']}** |",
                   f"| Atualizados | {banco['atualizados']} |",
                   f"| Já existiam | {banco['ja_existiam']} |"]
    linhas += [f"| Duração | {segundos / 60:.1f} min |", ""]
    if res.falhas:
        linhas += ["<details><summary>Primeiras falhas</summary>", "", "```"]
        linhas += [f"{i}: {erro}" for i, erro in res.falhas[:20]]
        linhas += ["```", "</details>"]
    return "\n".join(linhas) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(prog="python -m coleta", description="Coleta de peptídeos para o PlantAMP")
    p.add_argument("--fonte", required=True, choices=FONTES)
    p.add_argument("--modo", default="novos", choices=MODOS,
                   help="novos: só insere sequências novas | sincronizar: também atualiza as desta fonte | csv: não grava")
    p.add_argument("--inicio", type=int, default=1, help="primeiro id numérico (PlantPepDB e dbAMP)")
    p.add_argument("--limite", type=int, default=0, help="coleta só N ids (para testar); 0 = todos")
    p.add_argument("--workers", type=int, default=None, help="requisições simultâneas (padrão da fonte)")
    p.add_argument("--saida", default="saida", help="pasta onde salvar os CSVs")
    p.add_argument("--max-falhas", type=float, default=0.05,
                   help="aborta sem gravar se mais que esta fração dos ids falhar (padrão 5%%)")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stdout)
    if args.inicio < 1 or args.limite < 0:
        p.error("--inicio deve ser >= 1 e --limite >= 0")

    mod = importlib.import_module(FONTES[args.fonte])
    workers = args.workers or mod.WORKERS
    log.info("== %s | modo=%s | inicio=%d | limite=%s | workers=%d ==",
             mod.NOME, args.modo, args.inicio, args.limite or "todos", workers)

    t0 = time.time()
    res, df = mod.executar(inicio=args.inicio, limite=args.limite, workers=workers)
    log.info("Coleta terminou: %d registros lidos, %d inexistentes, %d falhas, %d linhas únicas",
             len(res.registros), res.inexistentes, len(res.falhas), len(df))

    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    if len(df):
        # utf-8 sem BOM: é o que o POST /api/peptides/import espera
        df.to_csv(saida / f"{args.fonte}.csv", index=False, encoding="utf-8")
        log.info("CSV salvo em %s", saida / f"{args.fonte}.csv")

    erro = None
    if not len(df):
        erro = "Nenhum registro coletado. O site pode estar fora do ar ou ter mudado de layout."
    elif res.taxa_falha > args.max_falhas:
        erro = (f"{res.taxa_falha:.1%} dos ids falharam (limite {args.max_falhas:.0%}). "
                "Nada foi gravado no banco; tente de novo mais tarde.")

    banco = None
    if erro is None and args.modo != "csv":
        con = conectar()
        try:
            banco = gravar(con, df, mod.NOME, args.modo)
        finally:
            con.close()

    resumo = _resumo_markdown(mod.NOME, args, res, df, banco, time.time() - t0)
    if erro:
        resumo += f"\n> **Erro:** {erro}\n"
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(resumo)
    print(resumo)

    if erro:
        log.error(erro)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())