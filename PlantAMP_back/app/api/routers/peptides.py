from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from typing import Optional, List
import pandas as pd
import duckdb
import io

from app.schemas.peptide import PeptideCreate, PeptideResponse, PeptideUpdate
from app.api.dependencies import CurrentUser, client_ip, get_database, require_permission
from app.core.config import settings
from app.services.accounts import audit

router = APIRouter(prefix="/peptides", tags=["Peptides"])


# ======================================================================
# LEITURA — PÚBLICA (qualquer pessoa, sem login)
# ======================================================================
@router.get("/", response_model=List[PeptideResponse])
def get_peptides(
    db: duckdb.DuckDBPyConnection = Depends(get_database),
    name: Optional[str] = Query(None),
    sequence: Optional[str] = Query(None),
    organism: Optional[str] = Query(None),
    activity: Optional[str] = Query(None),
    fonte: Optional[str] = Query(None)
):
    query = "SELECT * FROM peptides WHERE 1=1"
    params = []

    if name:
        query += " AND name ILIKE ?"
        params.append(f"%{name}%")
    if sequence:
        query += " AND sequence = ?"
        params.append(sequence)
    if organism:
        query += " AND organism ILIKE ?"
        params.append(f"%{organism}%")
    if activity:
        query += " AND activity ILIKE ?"
        params.append(f"%{activity}%")
    if fonte:
        query += " AND fonte ILIKE ?"
        params.append(f"%{fonte}%")

    query += " ORDER BY id DESC"

    try:
        df = db.execute(query, params).fetchdf()
        df = df.astype(object).where(pd.notnull(df), None)
        return df.to_dict(orient="records")
    except Exception:
        raise HTTPException(status_code=500, detail="Erro ao consultar peptídeos.")


@router.get("/{id}", response_model=PeptideResponse)
def get_peptide_by_id(id: int, db: duckdb.DuckDBPyConnection = Depends(get_database)):
    db.execute("SELECT * FROM peptides WHERE id = ?", (id,))
    result = db.fetchone()
    if not result:
        raise HTTPException(status_code=404, detail="Peptídeo não encontrado.")
    columns = [desc[0] for desc in db.description]
    return dict(zip(columns, result))


# ======================================================================
# ESCRITA — exige login + permissão da matriz de acesso
# ======================================================================
@router.post("/", response_model=PeptideResponse, status_code=201)
def create_peptide(
    peptide: PeptideCreate,
    request: Request,
    user: CurrentUser = Depends(require_permission("peptides:create")),
    db: duckdb.DuckDBPyConnection = Depends(get_database),
):
    try:
        db.execute("""
            INSERT INTO peptides
            (name, sequence, organism, activity, validation, uniprot, pdb, reference, pubmed, fonte)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING *
        """, (
            peptide.name, peptide.sequence, peptide.organism, peptide.activity,
            peptide.validation, peptide.uniprot, peptide.pdb, peptide.reference,
            peptide.pubmed, peptide.fonte
        ))
        result = db.fetchone()
        columns = [desc[0] for desc in db.description]
        created = dict(zip(columns, result))
    except duckdb.ConstraintException:
        raise HTTPException(status_code=400, detail="A sequência informada já existe no banco.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    audit(db, "peptide_created", user.id, f"id={created['id']}", client_ip(request))
    return created


@router.post("/import", status_code=201, summary="Importar base via CSV")
async def import_peptides_csv(
    request: Request,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_permission("peptides:import")),
    db: duckdb.DuckDBPyConnection = Depends(get_database),
):
    if not file.filename or not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="O arquivo deve ser .csv")

    max_bytes = settings.MAX_CSV_MB * 1024 * 1024
    contents = await file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise HTTPException(status_code=413, detail=f"CSV maior que {settings.MAX_CSV_MB} MB.")

    try:
        df = pd.read_csv(io.StringIO(contents.decode('utf-8')))

        # Colunas opcionais: se não vierem no CSV (ou vierem vazias) => 'Not found'
        for col in ('uniprot', 'pdb'):
            df[col] = df[col].fillna('Not found') if col in df.columns else 'Not found'
        if 'fonte' not in df.columns:
            df['fonte'] = None

        # Omitindo o campo ID no INSERT, o DuckDB utiliza o valor DEFAULT (que é o nextval da sequence)
        db.register("csv_df", df)
        try:
            db.execute("""
                INSERT INTO peptides
                (name, sequence, organism, activity, validation, uniprot, pdb, reference, pubmed, fonte)
                SELECT name, sequence, organism, activity, validation, uniprot, pdb, reference, pubmed, fonte
                FROM csv_df
            """)
        finally:
            db.unregister("csv_df")
    except duckdb.ConstraintException:
        raise HTTPException(status_code=400, detail="Erro: O CSV contém sequências que já existem no banco (conflito UNIQUE).")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na importação: {str(e)}")

    audit(db, "peptides_imported", user.id, f"{file.filename}: {len(df)} linhas", client_ip(request))
    return {"message": f"Sucesso! {len(df)} registros processados. IDs gerados automaticamente."}


@router.patch("/{id}", response_model=PeptideResponse)
@router.put("/{id}", response_model=PeptideResponse)
def update_peptide(
    id: int,
    peptide: PeptideUpdate,
    request: Request,
    user: CurrentUser = Depends(require_permission("peptides:update")),
    db: duckdb.DuckDBPyConnection = Depends(get_database),
):
    # exclude_unset=True garante que atualizaremos apenas os campos enviados no JSON
    update_data = peptide.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(status_code=400, detail="Nenhum dado fornecido para atualização.")

    # As chaves vêm do schema PeptideUpdate (lista fechada), então é seguro montar o SET
    set_clause = ", ".join([f"{key} = ?" for key in update_data.keys()])
    values = list(update_data.values())
    values.append(id)

    try:
        db.execute(f"UPDATE peptides SET {set_clause} WHERE id = ? RETURNING *", values)
        result = db.fetchone()
    except duckdb.ConstraintException:
        raise HTTPException(status_code=400, detail="Erro: A nova sequência informada já existe no banco.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not result:
        raise HTTPException(status_code=404, detail="Peptídeo não encontrado.")
    columns = [desc[0] for desc in db.description]
    audit(db, "peptide_updated", user.id, f"id={id} fields={sorted(update_data)}", client_ip(request))
    return dict(zip(columns, result))


@router.delete("/{id}")
def delete_peptide(
    id: int,
    request: Request,
    user: CurrentUser = Depends(require_permission("peptides:delete")),
    db: duckdb.DuckDBPyConnection = Depends(get_database),
):
    db.execute("DELETE FROM peptides WHERE id = ? RETURNING id", (id,))
    result = db.fetchone()
    if not result:
        raise HTTPException(status_code=404, detail="Peptídeo não encontrado.")
    audit(db, "peptide_deleted", user.id, f"id={id}", client_ip(request))
    return {"message": "Peptídeo deletado com sucesso.", "id": id}
