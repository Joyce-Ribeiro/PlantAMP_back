"""
Coletores de dados do PlantAMP (substituem o notebook limpeza_base.ipynb).

Cada fonte tem um módulo com duas funções:
    buscar(sessao, identificador)  -> baixa e lê um registro (None = não existe)
    tratar(registros)              -> DataFrame no formato da tabela `peptides`

Uso (da raiz do projeto):
    python -m coleta --fonte plantpepdb --modo csv
    python -m coleta --fonte dbamp --modo novos --inicio 35000
    python -m coleta --fonte apd --modo sincronizar

No GitHub Actions, os workflows em .github/workflows/coleta-*.yml rodam
exatamente esses comandos.
"""