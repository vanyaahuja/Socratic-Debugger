from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from api.leetcode import current_user
from database.db import get_db
from models import RevisionJournal, User
from schemas import JournalOut, JournalPatch
from services.journal_service import backfill_drafts, plain_pointer

router = APIRouter(prefix="/ext/journal", tags=["revision journal"])


def output(row):
    return JournalOut(id=row.id, problem_title=row.problem.title, problem_url=row.problem.url,
        how_found=row.how_found, how_fixed=row.how_fixed, takeaway=row.takeaway,
        outcome=row.outcome, uncertain=row.uncertain, edited=row.edited,
        reviewed=row.reviewed, updated_at=row.updated_at)


def own(db, user, entry_id):
    row = db.query(RevisionJournal).filter_by(id=entry_id, user_id=user.id).first()
    if row is None:
        raise HTTPException(404, "Journal entry not found.")
    return row


@router.get("", response_model=list[JournalOut])
def entries(user: User = Depends(current_user), db: Session = Depends(get_db)):
    backfill_drafts(db, user.id)
    rows = db.query(RevisionJournal).filter_by(user_id=user.id).order_by(RevisionJournal.updated_at.desc()).all()
    return [output(row) for row in rows]


@router.patch("/{entry_id}", response_model=JournalOut)
def edit(entry_id: int, payload: JournalPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = own(db, user, entry_id)
    for field in ("how_found", "how_fixed", "takeaway"):
        value = getattr(payload, field)
        if value is not None:
            if value.strip() and not plain_pointer(value):
                raise HTTPException(422, "Keep journal notes in plain language, without code snippets.")
            setattr(row, field, value.strip())
            row.edited = True
    if payload.reviewed is not None:
        row.reviewed = payload.reviewed
    row.updated_at = datetime.utcnow()
    db.commit()
    return output(row)
