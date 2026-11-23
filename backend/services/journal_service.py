"""Persist prose notes separately from tutor confidence and temporary code snapshots."""
import re
import hashlib
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from models import RevisionJournal, Session as SessionModel, Problem, Attempt


def plain_pointer(value, codes=()):
    value = (value or "").strip()
    if '`' in value or re.search(r"(?:^|\n)\s*(?:def\s|class\s|#include|(?:const|let|var)\s)|\b\w+\s*(?:=(?!=)|\+=|-=|\+\+)|\b(?:return|throw|raise)\s+\w+(?:\s*[;([{]|$)", value):
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
    if row.edited:
        return
    if hint.used_fallback or not hint.journal_note:
        if row.notes_status == "insufficient_evidence" and row.how_found and row.takeaway:
            return
        row.notes_status = "provider_unavailable" if hint.used_fallback else "model_omitted"
        db.commit()
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
        row.generation_token = None
    row.notes_status = ("ready" if row.how_found and row.how_fixed and row.takeaway else
                        "partial" if row.how_found or row.takeaway else "filtered")
    db.commit()


def journal_context(db, row):
    """Recover retained versions for old entries as well as the current turn."""
    attempts = db.query(Attempt).join(SessionModel).filter(
        SessionModel.user_id == row.user_id, SessionModel.problem_id == row.problem_id,
        Attempt.submitted_code != "").order_by(Attempt.id.desc()).all()
    if not attempts:
        return None
    accepted = [a for a in attempts if a.verdict == "accepted"]
    target = accepted[0] if row.outcome != "in_progress" and accepted else attempts[0]
    previous = next((a for a in attempts if a.id < target.id and a.session_id == target.session_id
                     and a.verdict != "accepted" and a.submitted_code.strip() != target.submitted_code.strip()), None)
    code, earlier = target.submitted_code, previous.submitted_code if previous else None
    fingerprint = hashlib.sha256(repr((target.id, code, earlier, target.verdict,
                                      target.verdict_source, target.feedback)).encode()).hexdigest()
    return dict(code=code, previous_code=earlier, target_id=target.id, language=target.language,
        verdict=target.verdict or "unknown", previous_verdict=previous.verdict if previous else "unknown",
        feedback=target.feedback or "", may_explain_fix=bool(earlier and target.verdict == "accepted"),
        uncertain=not previous or previous.verdict not in ("wrong_answer", "runtime_error", "compile_error", "time_limit_exceeded", "memory_limit_exceeded")
                  or previous.verdict_source != "page" or len(code) > 12000 or len(earlier or "") > 12000,
        fingerprint=fingerprint)


REASONS = {
    "model_omitted": "The tutor replied without revision notes. Saved code is available for a dedicated note request.",
    "filtered": "The generated text was empty or contained source snippets, so it was not saved. Try generating prose notes again.",
    "rate_limited": "The AI provider reached a usage limit. Your saved history is intact; try again later.",
    "authentication": "The AI provider rejected access. Check the backend provider settings, then retry.",
    "configuration": "The backend AI provider configuration needs attention before notes can be generated.",
    "invalid_output": "The AI did not return usable prose notes. Try generating them again.",
    "provider_unavailable": "The AI could not generate notes. Your saved versions are intact; retry when it is available.",
    "insufficient_evidence": "Partial notes are saved, but the code comparison did not establish a specific correction. Review or edit the explanation.",
}


def journal_state(db, row):
    if row.how_found and row.how_fixed and row.takeaway:
        return dict(notes_status="ready", pending_reason="", can_generate=False)
    if row.edited:
        return dict(notes_status="manual", pending_reason="These notes are edited by you. Fill any remaining sections with Edit notes.", can_generate=False)
    if row.generation_token and row.generation_started_at and (datetime.utcnow() - row.generation_started_at).total_seconds() < 45:
        return dict(notes_status="generating", pending_reason="Generating simple notes from the saved code versions…", can_generate=False)
    context = journal_context(db, row)
    if context is None:
        return dict(notes_status="missing_history", pending_reason="No code version is retained for this entry. Add notes manually; older discarded code cannot be reconstructed.", can_generate=False)
    if context['verdict'] == 'accepted' and not context['may_explain_fix']:
        return dict(notes_status="missing_baseline", pending_reason="The accepted version is saved, but a different earlier version is missing. A fix cannot be inferred from the accepted code alone.", can_generate=False)
    reason = REASONS.get(row.notes_status)
    if not reason:
        reason = ("Saved before/after versions are available. Generate revision notes from them."
                  if context['may_explain_fix'] else "A code version is saved. Generate a clue now; a fix needs a changed, solved version.")
    return dict(notes_status=row.notes_status or "pending", pending_reason=reason, can_generate=True)


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
