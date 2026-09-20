from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from database.db import get_db
from database.repositories import (
    add_tutor_interaction, get_session, get_problem,
)
from services.progress_service import determine_hint_level, record_outcome
from services.tutor_service import get_hint
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

    add_tutor_interaction(db, attempt_id=attempt.id, hint_level=hint.hint_level, question=hint.question)
    return hint


@router.post("/{attempt_id}/reasoning")
def submit_reasoning(attempt_id: int, payload: ReasoningSubmit, db: DBSession = Depends(get_db)):
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
    return {"status": "recorded"}
