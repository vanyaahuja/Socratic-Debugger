"""Persist prose notes separately from tutor confidence and temporary code snapshots."""
import re
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from models import RevisionJournal, Session as SessionModel, Problem


def plain_pointer(value, codes=()):
    value = (value or "").strip()
    if '`' in value or re.search(r"(?:^|\n)\s*(?:def\s|class\s|#include|(?:const|let|var)\s)|\b\w+\s*(?:=(?!=)|\+=|-=|\+\+)", value):
        return ""
    # Reject copied source lines, including unfenced code.
    lines = [line.strip() for code in codes for line in (code or "").splitlines() if len(line.strip()) >= 12]
    return "" if any(line in value for line in lines) else value


def ensure_entry(db, user_id, problem_id):
    row = db.query(RevisionJournal).filter_by(user_id=user_id, problem_id=problem_id).first()
    if row is None:
        row = RevisionJournal(user_id=user_id, problem_id=problem_id)
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # Concurrent first access must not create a duplicate.
            row = db.query(RevisionJournal).filter_by(user_id=user_id, problem_id=problem_id).one()
    return row


def begin_turn(db, user_id, problem_id, verdict, source, kind):
    row = ensure_entry(db, user_id, problem_id)
    if verdict == "accepted" and source == "page" and kind == "submit":
        row.outcome = "verified_accepted"
    elif verdict == "accepted" and source == "user_reported" and row.outcome != "verified_accepted":
        row.outcome = "user_reported"
    # A later failed revision doesn't erase an earlier accepted fix.
    row.updated_at = datetime.utcnow()
    db.commit()  # The draft/outcome survive provider failure.
    return row


def update_notes(db, row, hint, *, previous_code, code, may_explain_fix, comparison_uncertain=False):
    if hint.used_fallback or not hint.journal_note or row.edited:
        return
    note = hint.journal_note
    changed = False
    for field in ("how_found", "how_fixed", "takeaway"):
        if field == "how_fixed" and not may_explain_fix:
            continue  # A proposed fix in chat is not an observed code correction.
        value = plain_pointer(getattr(note, field), (previous_code, code))
        if value and value != getattr(row, field):
            setattr(row, field, value)
            changed = True
    if changed:
        row.uncertain = note.uncertain or comparison_uncertain
        row.reviewed = False
        row.updated_at = datetime.utcnow()
        db.commit()


def backfill_drafts(db, user_id):
    # Existing tutoring history remains discoverable, even if no old diagnosis
    # met the legacy confidence threshold. Never invent a historical code diff.
    sessions = (db.query(SessionModel).join(Problem).filter(
        SessionModel.user_id == user_id, Problem.source == "leetcode").all())
    for session in sessions:
        row = ensure_entry(db, user_id, session.problem_id)
        if session.solved:
            row.outcome = "verified_accepted"
    db.commit()
