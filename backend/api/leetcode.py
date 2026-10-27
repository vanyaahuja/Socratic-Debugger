"""
Chrome-extension API (/ext/*).

Kept separate from the original dev routes on purpose: every route here
requires an X-Profile-Token header, validates ownership, and is rate limited.
The extension generates a random token on first run; only its sha256 is stored,
so there is no account system and nothing to leak but a local profile.

Per-turn flow (analyze / reply): claim the session (-> ANALYZING) -> build a
minimal prompt -> tutor_service (never raises, falls back deterministically)
-> persist the turn -> journal a mistake only if evidence supports it -> set
the session state. Code is never executed here.
"""

import hashlib
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import or_, update
from sqlalchemy.orm import Session as DBSession

from database.db import get_db
from database.repositories import (
    add_tutor_interaction, create_attempt, create_session, get_session, next_attempt_number,
)
from models import (
    Attempt, ConceptProgress, MistakeObservation, Problem, Session as SessionModel,
    TestResult, TutorInteraction, User,
)
from schemas import (
    AnalyzeRequest, AnalyzeResponse, ExplainRequest, MistakeOut, MistakePatch, ProblemContext,
    ReplyRequest, RevisionReply, SessionView, TranscriptMessage, TutorHint,
)
from services.progress_service import (
    leetcode_hint_level, learner_patterns, learner_summary, patterns_for_prompt,
    record_mistake, record_outcome, resolve_session_mistakes, should_record_mistake,
)
from services.tutor_service import get_leetcode_hint, get_revision_response

router = APIRouter(prefix="/ext", tags=["extension"])

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
SESSION_REUSE_WINDOW = timedelta(hours=12)
ANALYZING_TIMEOUT = timedelta(seconds=45)
KEEP_CODE_FOR_LAST_N_ATTEMPTS = 2

# ---- rate limiting (in-memory, per process: fine for a single local backend) ----
ANALYZE_PER_MINUTE = 12
GENERAL_PER_MINUTE = 120
_hits: dict[tuple[int, str], deque] = defaultdict(deque)


def rate_limit(user_id: int, bucket: str, max_calls: int, window_s: int = 60) -> None:
    now = time.monotonic()
    q = _hits[(user_id, bucket)]
    while q and now - q[0] > window_s:
        q.popleft()
    if len(q) >= max_calls:
        retry = int(window_s - (now - q[0])) + 1
        raise HTTPException(status_code=429, detail="Too many requests, slow down.",
                            headers={"Retry-After": str(retry)})
    q.append(now)


# ---- auth ----
def current_user(x_profile_token: str | None = Header(default=None), db: DBSession = Depends(get_db)) -> User:
    if not x_profile_token or not TOKEN_RE.match(x_profile_token):
        raise HTTPException(status_code=401, detail="Missing or invalid profile token.")
    digest = hashlib.sha256(x_profile_token.encode()).hexdigest()
    user = db.query(User).filter(User.token_hash == digest).first()
    if user is None:
        user = User(name="Local profile", token_hash=digest)
        db.add(user)
        db.commit()
        db.refresh(user)
    rate_limit(user.id, "general", GENERAL_PER_MINUTE)
    return user


# ---- helpers ----
def _problem_for(db: DBSession, ctx: ProblemContext, language: str) -> Problem:
    """LeetCode problems are stored by identity only (slug/number/title/url)."""
    p = db.query(Problem).filter(Problem.source == "leetcode", Problem.external_slug == ctx.slug).first()
    url = ctx.url or f"https://leetcode.com/problems/{ctx.slug}/"
    if p is None:
        p = Problem(
            title=ctx.title or ctx.slug.replace("-", " ").title(), description="",
            difficulty=ctx.difficulty or "unknown", concept="leetcode", bug_category="external",
            language=language, starter_code="", reference_solution="", tests={},
            source="leetcode", external_slug=ctx.slug, external_id=ctx.frontend_id, url=url)
        db.add(p)
    else:
        if ctx.title and p.title != ctx.title:
            p.title = ctx.title
        if ctx.frontend_id and not p.external_id:
            p.external_id = ctx.frontend_id
    db.commit()
    db.refresh(p)
    return p


def _resolve_session(db: DBSession, user: User, problem: Problem, session_id: int | None) -> SessionModel:
    if session_id is not None:
        s = get_session(db, session_id)
        # 404 (not 403) so another user's session ids can't be probed.
        if s is None or s.user_id != user.id or s.problem_id != problem.id:
            raise HTTPException(status_code=404, detail="Session not found.")
        return s
    s = (db.query(SessionModel)
         .filter(SessionModel.user_id == user.id, SessionModel.problem_id == problem.id,
                 SessionModel.solved.is_(False),
                 SessionModel.started_at >= datetime.utcnow() - SESSION_REUSE_WINDOW)
         .order_by(SessionModel.id.desc()).first())
    return s or create_session(db, user.id, problem.id)


def _own_session(db: DBSession, user: User, session_id: int) -> SessionModel:
    s = get_session(db, session_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found.")
    return s


def _claim(db: DBSession, session: SessionModel) -> str:
    """Atomically move to ANALYZING; a second concurrent request gets 409."""
    prior = session.state
    now = datetime.utcnow()
    res = db.execute(update(SessionModel).where(
        SessionModel.id == session.id,
        or_(SessionModel.state != "ANALYZING", SessionModel.state_updated_at.is_(None),
            SessionModel.state_updated_at < now - ANALYZING_TIMEOUT),
    ).values(state="ANALYZING", state_updated_at=now))
    db.commit()
    if res.rowcount == 0:
        raise HTTPException(status_code=409, detail="An analysis is already running for this problem.")
    db.refresh(session)
    return prior


def _set_state(db: DBSession, session: SessionModel, state: str) -> None:
    session.state, session.state_updated_at = state, datetime.utcnow()
    db.commit()


def _interactions(db: DBSession, session_id: int) -> list[TutorInteraction]:
    return (db.query(TutorInteraction).join(Attempt, TutorInteraction.attempt_id == Attempt.id)
            .filter(Attempt.session_id == session_id)
            .order_by(TutorInteraction.id.asc()).all())


def _history(db: DBSession, session_id: int) -> list[tuple[str, str | None]]:
    return [(i.tutor_question, i.student_response) for i in _interactions(db, session_id)]


def _prune_old_code(db: DBSession, session_id: int) -> None:
    """Don't keep source snapshots: only the latest couple of attempts keep code."""
    old = (db.query(Attempt).filter(Attempt.session_id == session_id)
           .order_by(Attempt.attempt_number.desc()).offset(KEEP_CODE_FOR_LAST_N_ATTEMPTS).all())
    for a in old:
        a.submitted_code = ""
    db.commit()


def _state_after(hint: TutorHint) -> str:
    wants_edit = (hint.response_type == "instruction"
                  or hint.reasoning_stage in ("formulate_fix", "implement_fix", "resolved"))
    return "REVISION_PENDING" if wants_edit else "HINT_AVAILABLE"


def _failing_detail(feedback: str | None) -> bool:
    return bool(feedback and re.search(r"expected|input|output", feedback, re.IGNORECASE))


def _mistake_out(row: MistakeObservation) -> MistakeOut:
    pr = row.problem
    return MistakeOut(
        id=row.id, problem_title=pr.title, problem_slug=pr.external_slug, problem_number=pr.external_id,
        problem_url=pr.url, category=row.category, concept=row.concept,
        what_went_wrong=row.what_went_wrong, why_happened=row.why_happened,
        revision_hint=row.revision_hint, is_hypothesis=row.is_hypothesis, confidence=row.confidence,
        evidence=row.evidence, status=row.status, reviewed=row.reviewed,
        marked_for_revision=row.marked_for_revision, occurrences=row.occurrences,
        first_seen=row.first_seen, last_seen=row.last_seen, resolved_at=row.resolved_at)


def _own_mistake(db: DBSession, user: User, mistake_id: int) -> MistakeObservation:
    row = db.query(MistakeObservation).filter(
        MistakeObservation.id == mistake_id, MistakeObservation.user_id == user.id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Mistake not found.")
    return row


# ---- the shared tutoring turn ----
def _tutor_turn(db: DBSession, user: User, session: SessionModel, problem: Problem, attempt: Attempt, *,
                code: str, language: str, statement: str, verdict: str, source: str, kind: str,
                feedback: str | None, passed: int | None, total: int | None, prev: Attempt | None,
                code_changed: bool, request_explanation: bool, user_message: str | None,
                escalate: bool, missing: list[str], new_attempt: bool):
    verified = verdict == "accepted" and source == "page" and kind == "submit"
    # An unverified "accepted" must not unlock the Accepted-only transfer check.
    ladder_verdict = verdict if (verdict != "accepted" or verified) else "unknown"
    if verdict == "accepted" and not verified:
        feedback = ((feedback or "") + " [Student reports it now passes; this is NOT verified.]").strip()

    level = leetcode_hint_level(
        verdict=ladder_verdict, highest=session.highest_hint_level, previous=prev,
        code_changed=code_changed, passed=passed, total=total,
        request_explanation=request_explanation, escalate=escalate)

    patterns = learner_patterns(db, user.id)
    hint = get_leetcode_hint(
        hint_level=level, verdict=ladder_verdict, verdict_source=source, verdict_kind=kind,
        feedback=feedback, has_failing_detail=_failing_detail(feedback),
        problem_title=problem.title, statement=statement, language=language, code=code,
        testcases=(f"{passed}/{total} passed" if passed is not None and total else None),
        previous_attempt=("first analysis in this session" if prev is None else
                          f"code {'edited' if code_changed else 'UNCHANGED'} since the previous attempt "
                          f"(previous verdict: {prev.verdict or 'unknown'})"),
        history=_history(db, session.id), user_message=user_message,
        request_explanation=request_explanation,
        profile_lines=patterns_for_prompt(patterns, ladder_verdict), missing_context=missing)

    add_tutor_interaction(db, attempt_id=attempt.id, hint_level=hint.hint_level, question=hint.message)

    mistake_id, note, recorded = None, None, False
    if verified:
        # Resolve using the level reached BEFORE this Accepted turn.
        resolve_session_mistakes(db, user_id=user.id, session_id=session.id,
                                 highest_hint_level=session.highest_hint_level)
        for concept in {r.concept for r in db.query(MistakeObservation).filter(
                MistakeObservation.user_id == user.id, MistakeObservation.session_id == session.id)}:
            record_outcome(db, user.id, concept, solved=True, hint_level=session.highest_hint_level)
        session.solved, session.completed_at = True, datetime.utcnow()
        final_state = "SOLVED"
    else:
        session.highest_hint_level = max(session.highest_hint_level, level)
        ok, note = should_record_mistake(ladder_verdict, source, hint.diagnosis)
        if ok:
            row = record_mistake(
                db, user_id=user.id, problem=problem, session_id=session.id, diag=hint.diagnosis,
                verdict=ladder_verdict, hint_level=hint.hint_level, new_attempt=new_attempt,
                evidence_text=(f"{passed}/{total} testcases; " if passed is not None and total else "")
                              + (feedback or "")[:200])
            if new_attempt:
                record_outcome(db, user.id, hint.diagnosis.concept, solved=False, hint_level=hint.hint_level)
            mistake_id, recorded, note = row.id, True, None
        final_state = _state_after(hint)
    _set_state(db, session, final_state)
    return hint, level, verified, recorded, mistake_id, note, final_state


# ---- routes ----
@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(payload: AnalyzeRequest, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    rate_limit(user.id, "analyze", ANALYZE_PER_MINUTE)
    if not payload.code.strip():
        raise HTTPException(status_code=422, detail="No code was collected from the page.")

    problem = _problem_for(db, payload.problem, payload.language)
    session = _resolve_session(db, user, problem, payload.session_id)
    prior_state = _claim(db, session)
    try:
        sub = payload.submission
        code_hash = hashlib.sha256(payload.code.strip().encode()).hexdigest()
        prev = (db.query(Attempt).filter(Attempt.session_id == session.id)
                .order_by(Attempt.attempt_number.desc()).first())
        code_changed = prev is None or prev.code_hash != code_hash
        # Same code + same verdict as the last attempt = a repeated request, not a new attempt.
        duplicate = prev is not None and not code_changed \
            and prev.verdict == sub.status and prev.verdict_source == sub.source
        if duplicate:
            attempt = prev
        else:
            attempt = create_attempt(
                db, session_id=session.id, attempt_number=next_attempt_number(db, session.id),
                language=payload.language, submitted_code=payload.code, code_hash=code_hash,
                verdict=sub.status, verdict_source=sub.source,
                feedback=(sub.message or "")[:1000] or None,
                tests_passed=sub.testcases_passed or 0, tests_total=sub.testcases_total or 0)
            session.total_attempts = attempt.attempt_number
            db.commit()
            _prune_old_code(db, session.id)

        hint, level, verified, recorded, mistake_id, note, state = _tutor_turn(
            db, user, session, problem, attempt, code=payload.code, language=payload.language,
            statement=payload.problem.statement, verdict=sub.status, source=sub.source, kind=sub.kind,
            feedback=sub.message, passed=sub.testcases_passed, total=sub.testcases_total, prev=prev,
            code_changed=code_changed, request_explanation=payload.request_explanation,
            user_message=None, escalate=True, missing=payload.missing_context, new_attempt=not duplicate)
    except Exception:
        _set_state(db, session, prior_state if prior_state != "ANALYZING" else "READY")
        raise

    verification = ("verified_accepted" if verified else
                    "unverified_user_report" if sub.status == "accepted" else
                    "pending" if sub.status == "running" else "not_accepted")
    return AnalyzeResponse(
        session_id=session.id, attempt_id=attempt.id, attempt_number=attempt.attempt_number,
        state=state, hint_level=level, tutor=hint, solved=session.solved, verification=verification,
        mistake_recorded=recorded, mistake_id=mistake_id, mistake_note=note, duplicate_attempt=duplicate)


@router.post("/session/{session_id}/reply", response_model=AnalyzeResponse)
def reply(session_id: int, payload: ReplyRequest, user: User = Depends(current_user),
          db: DBSession = Depends(get_db)):
    """The student answers the tutor. Same turn pipeline, but a conversational
    reply never escalates the hint level and never creates an attempt."""
    rate_limit(user.id, "analyze", ANALYZE_PER_MINUTE)
    session = _own_session(db, user, session_id)
    problem = db.get(Problem, session.problem_id)
    attempt = (db.query(Attempt).filter(Attempt.session_id == session.id)
               .order_by(Attempt.attempt_number.desc()).first())
    interactions = _interactions(db, session.id)
    if attempt is None or not interactions:
        raise HTTPException(status_code=409, detail="Ask for help on your code first.")

    prior_state = _claim(db, session)
    try:
        interactions[-1].student_response = payload.message
        db.commit()
        prev = (db.query(Attempt).filter(Attempt.session_id == session.id, Attempt.id != attempt.id)
                .order_by(Attempt.attempt_number.desc()).first())
        verdict, source = attempt.verdict or "unknown", attempt.verdict_source or "none"
        hint, level, verified, recorded, mistake_id, note, state = _tutor_turn(
            db, user, session, problem, attempt, code=attempt.submitted_code, language=attempt.language,
            statement=payload.statement, verdict=verdict, source=source,
            kind="submit" if source == "page" else "none", feedback=attempt.feedback,
            passed=attempt.tests_passed or None, total=attempt.tests_total or None, prev=prev,
            code_changed=False, request_explanation=False, user_message=payload.message,
            escalate=False, missing=[], new_attempt=False)
        if session.solved:  # a chat after a verified solve stays SOLVED
            _set_state(db, session, "SOLVED")
            state = "SOLVED"
    except Exception:
        _set_state(db, session, prior_state if prior_state != "ANALYZING" else "READY")
        raise
    return AnalyzeResponse(
        session_id=session.id, attempt_id=attempt.id, attempt_number=attempt.attempt_number,
        state=state, hint_level=level, tutor=hint, solved=session.solved,
        verification="verified_accepted" if session.solved else "not_accepted",
        mistake_recorded=recorded, mistake_id=mistake_id, mistake_note=note, duplicate_attempt=False)


def _session_view(db: DBSession, s: SessionModel) -> SessionView:
    msgs: list[TranscriptMessage] = []
    for i in _interactions(db, s.id):
        msgs.append(TranscriptMessage(sender="tutor", text=i.tutor_question))
        if i.student_response:
            msgs.append(TranscriptMessage(sender="student", text=i.student_response))
    problem = db.get(Problem, s.problem_id)
    return SessionView(session_id=s.id, state=s.state, solved=s.solved,
                       highest_hint_level=s.highest_hint_level,
                       problem_slug=problem.external_slug if problem else None, messages=msgs)


@router.get("/session/by-slug/{slug}", response_model=SessionView | None)
def session_by_slug(slug: str, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    """Restore the conversation when the side panel reopens or the student
    navigates back to a problem."""
    problem = db.query(Problem).filter(Problem.source == "leetcode", Problem.external_slug == slug).first()
    if problem is None:
        return None
    s = (db.query(SessionModel)
         .filter(SessionModel.user_id == user.id, SessionModel.problem_id == problem.id,
                 SessionModel.started_at >= datetime.utcnow() - SESSION_REUSE_WINDOW)
         .order_by(SessionModel.id.desc()).first())
    return _session_view(db, s) if s else None


@router.get("/session/{session_id}", response_model=SessionView)
def session_detail(session_id: int, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    return _session_view(db, _own_session(db, user, session_id))


@router.get("/mistakes", response_model=list[MistakeOut])
def list_mistakes(view: str = "recent", q: str | None = None, category: str | None = None,
                  concept: str | None = None, status: str | None = None, limit: int = 100,
                  user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    query = (db.query(MistakeObservation).join(Problem, MistakeObservation.problem_id == Problem.id)
             .filter(MistakeObservation.user_id == user.id))
    if view == "needs_revision":
        query = query.filter(or_(MistakeObservation.status == "unresolved",
                                 MistakeObservation.marked_for_revision.is_(True)))
    elif view == "resolved":
        query = query.filter(MistakeObservation.status != "unresolved")
    elif view not in ("recent", "all"):
        raise HTTPException(status_code=422, detail="Unknown view.")
    if category:
        query = query.filter(MistakeObservation.category == category)
    if status:
        query = query.filter(MistakeObservation.status == status)
    if concept:
        query = query.filter(MistakeObservation.concept.ilike(f"%{concept}%"))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Problem.title.ilike(like), Problem.external_id.ilike(like),
                                 Problem.external_slug.ilike(like), MistakeObservation.category.ilike(like),
                                 MistakeObservation.concept.ilike(like)))
    rows = query.order_by(MistakeObservation.last_seen.desc()).limit(max(1, min(limit, 200))).all()
    return [_mistake_out(r) for r in rows]


@router.patch("/mistakes/{mistake_id}", response_model=MistakeOut)
def patch_mistake(mistake_id: int, patch: MistakePatch, user: User = Depends(current_user),
                  db: DBSession = Depends(get_db)):
    row = _own_mistake(db, user, mistake_id)
    if patch.reviewed is not None:
        row.reviewed = patch.reviewed
    if patch.marked_for_revision is not None:
        row.marked_for_revision = patch.marked_for_revision
    db.commit()
    db.refresh(row)
    return _mistake_out(row)


@router.delete("/mistakes/{mistake_id}")
def delete_mistake(mistake_id: int, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    db.delete(_own_mistake(db, user, mistake_id))
    db.commit()
    return {"deleted": 1}


@router.post("/mistakes/{mistake_id}/explain", response_model=RevisionReply)
def explain_mistake(mistake_id: int, payload: ExplainRequest, user: User = Depends(current_user),
                    db: DBSession = Depends(get_db)):
    """Another Socratic nudge, or a practice question, from the saved summary only."""
    rate_limit(user.id, "analyze", ANALYZE_PER_MINUTE)
    row = _own_mistake(db, user, mistake_id)
    message, used_ai = get_revision_response(
        mode=payload.mode, problem_title=row.problem.title, category=row.category, concept=row.concept,
        what_went_wrong=row.what_went_wrong, why_happened=row.why_happened, revision_hint=row.revision_hint)
    return RevisionReply(message=message, mode=payload.mode, used_ai=used_ai)


@router.get("/patterns")
def patterns(user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    return learner_patterns(db, user.id)


@router.get("/summary")
def summary(user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    return learner_summary(db, user.id)


@router.delete("/history")
def delete_history(user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    """Delete everything stored about this profile (the profile row itself stays
    so the extension's token keeps working)."""
    session_ids = [i for (i,) in db.query(SessionModel.id).filter(SessionModel.user_id == user.id)]
    attempt_ids = ([i for (i,) in db.query(Attempt.id).filter(Attempt.session_id.in_(session_ids))]
                   if session_ids else [])
    counts = {"mistakes": db.query(MistakeObservation).filter(MistakeObservation.user_id == user.id)
              .delete(synchronize_session=False)}
    if attempt_ids:
        counts["interactions"] = db.query(TutorInteraction).filter(
            TutorInteraction.attempt_id.in_(attempt_ids)).delete(synchronize_session=False)
        db.query(TestResult).filter(TestResult.attempt_id.in_(attempt_ids)).delete(synchronize_session=False)
        counts["attempts"] = db.query(Attempt).filter(Attempt.id.in_(attempt_ids)).delete(synchronize_session=False)
    if session_ids:
        counts["sessions"] = db.query(SessionModel).filter(SessionModel.id.in_(session_ids)).delete(synchronize_session=False)
    counts["concept_progress"] = db.query(ConceptProgress).filter(
        ConceptProgress.user_id == user.id).delete(synchronize_session=False)
    db.commit()
    return {"deleted": counts}
