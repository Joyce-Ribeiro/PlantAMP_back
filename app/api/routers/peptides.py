from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from typing import Optional, List
import pandas as pd
import duckdb
import io

from app.schemas.peptide import PeptideCreate, PeptideResponse, PeptideUpdate
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

@router.get("/{id}", response_model=PeptideResponse)
def get_peptide_by_id(id: int, db: duckdb.DuckDBPyConnection = Depends(get_database)):
    db.execute("SELECT * FROM peptides WHERE id = ?", (id,))
    result = db.fetchone()
    if not result:
        raise HTTPException(status_code=404, detail="Peptídeo não encontrado.")
    columns = [desc[0] for desc in db.description]
    return dict(zip(columns, result))

@router.patch("/{id}", response_model=PeptideResponse)
@router.put("/{id}", response_model=PeptideResponse)
def update_peptide(id: int, peptide: PeptideUpdate, db: duckdb.DuckDBPyConnection = Depends(get_database)):
    # exclude_unset=True garante que atualizaremos apenas os campos enviados no JSON
    update_data = peptide.model_dump(exclude_unset=True)
    
    if not update_data:
        raise HTTPException(status_code=400, detail="Nenhum dado fornecido para atualização.")
    
    # Monta a query dinamicamente baseada nas chaves fornecidas
    set_clause = ", ".join([f"{key} = ?" for key in update_data.keys()])
    values = list(update_data.values())
    values.append(id)
    
    try:
        db.execute(f"UPDATE peptides SET {set_clause} WHERE id = ? RETURNING *", values)
        result = db.fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Peptídeo não encontrado.")
            
        columns = [desc[0] for desc in db.description]
        return dict(zip(columns, result))
    except duckdb.ConstraintException:
        raise HTTPException(status_code=400, detail="Erro: A nova sequência informada já existe no banco.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{id}")
def delete_peptide(id: int, db: duckdb.DuckDBPyConnection = Depends(get_database)):
    db.execute("DELETE FROM peptides WHERE id = ? RETURNING id", (id,))
    result = db.fetchone()
    if not result:
        raise HTTPException(status_code=404, detail="Peptídeo não encontrado.")
    return {"message": "Peptídeo deletado com sucesso.", "id": id}

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
            
        # Omitindo o campo ID no INSERT, o DuckDB utiliza o valor DEFAULT (que é o nextval da sequence)
        db.execute("""
            INSERT INTO peptides 
            (name, sequence, organism, activity, validation, uniprot, pdb, reference, pubmed, fonte) 
            SELECT name, sequence, organism, activity, validation, uniprot, pdb, reference, pubmed, fonte 
            FROM df
        """)
        
        return {"message": f"Sucesso! {len(df)} registros processados. IDs gerados automaticamente."}
    except duckdb.ConstraintException:
        raise HTTPException(status_code=400, detail="Erro: O CSV contém sequências que já existem no banco (conflito UNIQUE).")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na importação: {str(e)}")