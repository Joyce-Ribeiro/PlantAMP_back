"""Gravação no banco (MotherDuck ou arquivo .duckdb local)."""
import os

import duckdb
import pandas as pd

from coleta.comum import COLUNAS, log

MODOS = ("novos", "sincronizar", "csv")


def conectar() -> duckdb.DuckDBPyConnection:
    """Mesmas variáveis do .env da API: DATABASE_FILE e MOTHERDUCK_TOKEN."""
    destino = os.environ.get("DATABASE_FILE", "md:plantsamp_db")
    token = os.environ.get("MOTHERDUCK_TOKEN")
    if destino.startswith("md:"):
        if not token:
            raise SystemExit("MOTHERDUCK_TOKEN não definido (no GitHub: Settings → Secrets → Actions).")
        return duckdb.connect(destino, config={"motherduck_token": token})
    return duckdb.connect(destino)


def _tabela_existe(con, nome: str) -> bool:
    return con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = ? AND table_schema = current_schema()",
        [nome],
    ).fetchone() is not None


def gravar(con: duckdb.DuckDBPyConnection, df: pd.DataFrame, fonte: str, modo: str) -> dict:
    """
    novos:       insere só as sequências que ainda não estão no banco.
    sincronizar: além disso, atualiza as linhas que já existem E vieram desta
                 mesma fonte (nunca mexe em dados cadastrados à mão ou de outra fonte).
    Tudo numa transação: ou grava tudo, ou nada.
    """
    if modo not in ("novos", "sincronizar"):
        raise ValueError(f"modo inválido para gravar: {modo}")
    if not _tabela_existe(con, "peptides"):
        raise SystemExit("A tabela 'peptides' não existe neste banco. Suba a API uma vez para criá-la.")

    con.register("coleta_df", df[COLUNAS])
    campos = ", ".join(COLUNAS)
    atualizaveis = [c for c in COLUNAS if c not in ("sequence", "fonte")]
    try:
        con.execute("BEGIN TRANSACTION")
        ja_existiam = con.execute(
            "SELECT count(*) FROM coleta_df n JOIN peptides p ON p.sequence = n.sequence"
        ).fetchone()[0]

        atualizados = 0
        if modo == "sincronizar":
            sets = ", ".join(f"{c} = n.{c}" for c in atualizaveis)
            mudou = " OR ".join(f"p.{c} IS DISTINCT FROM n.{c}" for c in atualizaveis)
            atualizados = con.execute(
                f"UPDATE peptides AS p SET {sets} FROM coleta_df AS n "
                f"WHERE p.sequence = n.sequence AND p.fonte = ? AND ({mudou})",
                [fonte],
            ).fetchone()[0]

        inseridos = con.execute(
            f"INSERT INTO peptides ({campos}) SELECT {campos} FROM coleta_df AS n "
            "WHERE NOT EXISTS (SELECT 1 FROM peptides p WHERE p.sequence = n.sequence)"
        ).fetchone()[0]

        resumo = {"fonte": fonte, "modo": modo, "coletados": len(df), "inseridos": inseridos,
                  "atualizados": atualizados, "ja_existiam": ja_existiam}
        if _tabela_existe(con, "audit_log"):
            origem = "github-actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "terminal"
            detalhe = ", ".join(f"{k}={v}" for k, v in resumo.items()) + f", origem={origem}"
            con.execute("INSERT INTO audit_log (user_id, action, detail) VALUES (NULL, 'coleta', ?)", [detalhe])
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.unregister("coleta_df")

    log.info("Banco: %d inseridos, %d atualizados, %d já existiam", inseridos, atualizados, ja_existiam)
    return resumo