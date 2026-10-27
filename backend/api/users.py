from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from database.db import get_db
from models import ConceptProgress
from schemas import ProgressOut

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}/progress", response_model=list[ProgressOut])
def get_progress(user_id: int, db: DBSession = Depends(get_db)):
    """
    Equivalent SQL:
        SELECT concept, attempts, solved_count, average_hint_level
        FROM concept_progress WHERE user_id = :user_id;
    """
    return db.query(ConceptProgress).filter(ConceptProgress.user_id == user_id).all()
