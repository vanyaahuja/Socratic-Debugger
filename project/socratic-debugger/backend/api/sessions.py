from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from database.db import get_db
from database.repositories import create_session, get_session
from schemas import SessionCreate, SessionOut

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionOut)
def start_session(payload: SessionCreate, db: DBSession = Depends(get_db)):
    return create_session(db, user_id=payload.user_id, problem_id=payload.problem_id)


@router.get("/{session_id}", response_model=SessionOut)
def get_session_detail(session_id: int, db: DBSession = Depends(get_db)):
    session = get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session
