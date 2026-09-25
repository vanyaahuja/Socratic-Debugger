"""
Run vs Submit, per the spec, are genuinely different code paths -- not the
same handler with a flag. Run never touches the attempts table or the hint
system; Submit always does both.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from database.db import get_db
from database.repositories import (
    get_session, get_problem, next_attempt_number, create_attempt, add_test_results,
)
from services.execution_service import execute
from services.test_service import run_tests, to_public_results, summarize
from schemas import RunRequest, RunResult, SubmitAttemptRequest, SubmitAttemptResponse, TestResultPublic

router = APIRouter(prefix="/attempts", tags=["attempts"])


@router.post("", response_model=RunResult)
def run_code(payload: RunRequest, db: DBSession = Depends(get_db)):
    """Experimentation only: executes code and optionally runs visible
    tests. Does NOT create an Attempt row, does NOT touch hint level."""
    session = get_session(db, payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    problem = get_problem(db, session.problem_id)

    result = execute(payload.language, payload.code)

    visible_passed = visible_total = None
    if result.success and problem is not None:
        tests = problem.tests or {"visible": [], "hidden": []}
        visible_only = {"visible": tests.get("visible", []), "hidden": []}
        outcomes = run_tests(payload.language, payload.code, visible_only)
        visible_passed, visible_total = summarize(outcomes)

    return RunResult(
        success=result.success,
        stdout=result.stdout,
        stderr=result.stderr,
        error_type=result.error_type,
        error_message=result.error_message,
        visible_tests_passed=visible_passed,
        visible_tests_total=visible_total,
        execution_time_ms=result.execution_time_ms,
    )


@router.post("/submit", response_model=SubmitAttemptResponse)
def submit_attempt(payload: SubmitAttemptRequest, db: DBSession = Depends(get_db)):
    """Full pipeline: execute, run ALL tests (visible + hidden), persist
    the attempt, and leave hint-level/tutor invocation to the /hint
    endpoint (called separately by the frontend after showing results)."""
    session = get_session(db, payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    problem = get_problem(db, session.problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    result = execute(payload.language, payload.code)
    tests = problem.tests or {"visible": [], "hidden": []}
    outcomes = run_tests(payload.language, payload.code, tests) if result.success else []
    tests_passed, tests_total = summarize(outcomes) if outcomes else (0, len(tests.get("visible", [])) + len(tests.get("hidden", [])))

    attempt_number = next_attempt_number(db, session.id)
    attempt = create_attempt(
        db,
        session_id=session.id,
        attempt_number=attempt_number,
        language=payload.language,
        submitted_code=payload.code,
        compilation_success=result.compiled if payload.language == "cpp" else None,
        tests_passed=tests_passed,
        tests_total=tests_total,
        runtime_error=result.error_message if result.error_type == "runtime_error" else None,
        compiler_error=result.compiler_diagnostics,
        execution_time_ms=result.execution_time_ms,
    )

    if outcomes:
        add_test_results(db, attempt.id, [
            {
                "test_identifier": o.test_identifier,
                "passed": o.passed,
                "actual_output": o.actual_output,
                "error_type": o.error_type,
                "hidden": o.hidden,
            }
            for o in outcomes
        ])

    solved = tests_total > 0 and tests_passed == tests_total
    session.total_attempts = attempt_number
    if solved:
        session.solved = True
    db.commit()

    return SubmitAttemptResponse(
        attempt_id=attempt.id,
        attempt_number=attempt_number,
        compiled=result.compiled if payload.language == "cpp" else None,
        tests_passed=tests_passed,
        tests_total=tests_total,
        test_results=[TestResultPublic(test_identifier=o.test_identifier, passed=o.passed, hidden=o.hidden) for o in outcomes],
        compiler_error=result.compiler_diagnostics,
        runtime_error=result.error_message if result.error_type == "runtime_error" else None,
        solved=solved,
    )
