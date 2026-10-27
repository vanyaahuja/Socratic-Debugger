from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from database.db import get_db
from database.repositories import (
    add_tutor_interaction, get_session, get_problem,
)
from services.progress_service import determine_hint_level, record_outcome
from services.tutor_service import get_hint, respond_to_reasoning
from schemas import HintRequest, TutorHint, ReasoningSubmit
from models import Attempt, TutorInteraction

router = APIRouter(prefix="/attempts", tags=["tutor"])


@router.post("/{attempt_id}/hint", response_model=TutorHint)
def request_hint(attempt_id: int, db: DBSession = Depends(get_db)):
    attempt = db.query(Attempt).filter(Attempt.id == attempt_id).first()
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")
    session = get_session(db, attempt.session_id)
    problem = get_problem(db, session.problem_id)

    hint_level = determine_hint_level(
        db, session.id, attempt.attempt_number, attempt.tests_passed, session.highest_hint_level,
    )
    session.highest_hint_level = max(session.highest_hint_level, hint_level)
    db.commit()

    previous_interaction = (
        db.query(TutorInteraction)
        .filter(TutorInteraction.attempt_id == attempt_id)
        .order_by(TutorInteraction.created_at.desc())
        .first()
    )

    hint = get_hint(
        code=attempt.submitted_code,
        language=attempt.language,
        tests_passed=attempt.tests_passed,
        tests_total=attempt.tests_total,
        compiled=attempt.compilation_success,
        bug_category_signal=problem.bug_category,  # internal signal only, never returned to client
        hint_level=hint_level,
        previous_question=previous_interaction.tutor_question if previous_interaction else None,
        student_hypothesis=previous_interaction.student_response if previous_interaction else None,
        reference_solution=problem.reference_solution,
    )

    add_tutor_interaction(db, attempt_id=attempt.id, hint_level=hint.hint_level, question=hint.message)
    return hint


@router.post("/{attempt_id}/reasoning", response_model=TutorHint)
def submit_reasoning(attempt_id: int, payload: ReasoningSubmit, db: DBSession = Depends(get_db)):
    """
    Records the student's reasoning AND has the tutor actually reply to it
    -- this is the other half of a real conversation. The reply is stored
    as its own new TutorInteraction (same hint_level as the question it's
    answering; this is a conversational turn, not a formal re-assessment,
    so it doesn't go through determine_hint_level/escalation).
    """
    interaction = (
        db.query(TutorInteraction)
        .filter(TutorInteraction.attempt_id == attempt_id)
        .order_by(TutorInteraction.created_at.desc())
        .first()
    )
    if interaction is None:
        raise HTTPException(status_code=404, detail="No tutor interaction to respond to")
    interaction.student_response = payload.student_response
    db.commit()

    attempt = db.query(Attempt).filter(Attempt.id == attempt_id).first()
    session = get_session(db, attempt.session_id)
    problem = get_problem(db, session.problem_id)

    # Full transcript for this attempt, oldest first -- this is what fixes
    # the "tutor loops on a question I already answered" bug: without the
    # whole history, respond_to_reasoning only ever saw the single most
    # recent turn and had no memory of what was settled earlier.
    all_interactions = (
        db.query(TutorInteraction)
        .filter(TutorInteraction.attempt_id == attempt_id)
        .order_by(TutorInteraction.created_at.asc())
        .all()
    )
    conversation_history = [(i.tutor_question, i.student_response) for i in all_interactions]
    # The interaction we just answered (the last one, since student_response
    # was set above) would otherwise show up twice: once inside the history
    # and again as the "latest" response passed separately below. Blank its
    # response out of the history list to avoid that duplication.
    if conversation_history:
        last_q, _ = conversation_history[-1]
        conversation_history[-1] = (last_q, None)

    reply = respond_to_reasoning(
        code=attempt.submitted_code,
        language=attempt.language,
        tests_passed=attempt.tests_passed,
        tests_total=attempt.tests_total,
        hint_level=interaction.hint_level,
        conversation_history=conversation_history,
        student_response=payload.student_response,
        bug_category_signal=problem.bug_category,
        reference_solution=problem.reference_solution,
    )

    add_tutor_interaction(db, attempt_id=attempt.id, hint_level=reply.hint_level, question=reply.message)
    return reply
