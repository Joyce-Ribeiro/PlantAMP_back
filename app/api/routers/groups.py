from fastapi import APIRouter

router = APIRouter(prefix="/groups", tags=["Groups"])

@router.get("/")
def get_groups():
    return {"message": "Módulo de grupos em construção."}