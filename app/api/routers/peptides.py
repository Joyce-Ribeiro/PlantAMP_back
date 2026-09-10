from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from typing import Optional, List
import pandas as pd
import duckdb
import io

from app.schemas.peptide import PeptideCreate, PeptideResponse
from app.api.dependencies import get_database

router = APIRouter(prefix="/peptides", tags=["Peptides"])

@router.post("/", response_model=PeptideResponse, status_code=201)
def create_peptide(peptide: PeptideCreate, db: duckdb.DuckDBPyConnection = Depends(get_database)):
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
        return dict(zip(columns, result))
        
    except duckdb.ConstraintException:
        raise HTTPException(status_code=400, detail="A sequência informada já existe no banco.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
        df = df.where(pd.notnull(df), None) 
        return df.to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import", status_code=201, summary="Importar base via CSV")
async def import_peptides_csv(file: UploadFile = File(...), db: duckdb.DuckDBPyConnection = Depends(get_database)):
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="O arquivo deve ser .csv")
    
    try:
        contents = await file.read()
        df = pd.read_csv(io.StringIO(contents.decode('utf-8')))
        
        df['uniprot'] = df.get('uniprot', 'Not found').fillna('Not found')
        df['pdb'] = df.get('pdb', 'Not found').fillna('Not found')
        if 'fonte' not in df.columns:
            df['fonte'] = None
            
        db.execute("""
            INSERT INTO peptides 
            (name, sequence, organism, activity, validation, uniprot, pdb, reference, pubmed, fonte) 
            SELECT name, sequence, organism, activity, validation, uniprot, pdb, reference, pubmed, fonte 
            FROM df
        """)
        
        return {"message": f"Sucesso! {len(df)} registros processados."}
    except duckdb.ConstraintException:
        raise HTTPException(status_code=400, detail="Erro: O CSV contém sequências que já existem no banco (conflito UNIQUE).")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na importação: {str(e)}")