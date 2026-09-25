from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from database.db import get_db
from database.repositories import create_session, get_session, get_problem
from models import User
from schemas import SessionCreate, SessionOut

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionOut)
def start_session(payload: SessionCreate, db: DBSession = Depends(get_db)):
    # Checked explicitly (rather than letting the INSERT hit the FK
    # constraint) so a bad id returns a clean 404 instead of an unhandled
    # IntegrityError -- which crashes as a 500 with no CORS headers
    # attached, and shows up in the browser as a misleading "CORS error"
    # regardless of what actually went wrong.
    if db.query(User).filter(User.id == payload.user_id).first() is None:
        raise HTTPException(status_code=404, detail=f"No user with id {payload.user_id}")
    if get_problem(db, payload.problem_id) is None:
        raise HTTPException(status_code=404, detail=f"No problem with id {payload.problem_id}")
    return create_session(db, user_id=payload.user_id, problem_id=payload.problem_id)


@router.get("/{session_id}", response_model=SessionOut)
def get_session_detail(session_id: int, db: DBSession = Depends(get_db)):
    session = get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session