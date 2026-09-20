"""
Repository layer.

Purpose: isolate all direct DB access here so services never import
SQLAlchemy models directly. This is what makes the Postgres migration
"not a full redesign" -- services call repository functions; only this
file (and models/) needs to know what the underlying SQL looks like.

Each function has the raw-SQL equivalent in its docstring, per your request
to not hide SQL fundamentals behind the ORM.
"""

from sqlalchemy.orm import Session as DBSession
from models import (
    User, Problem, Session as SessionModel, Attempt, TestResult,
    TutorInteraction, ConceptProgress,
)


def get_problem(db: DBSession, problem_id: int) -> Problem | None:
    """
    Equivalent SQL:
        SELECT * FROM problems WHERE id = :problem_id;
    """
    return db.query(Problem).filter(Problem.id == problem_id).first()


def list_problems(db: DBSession) -> list[Problem]:
    """
    Equivalent SQL:
        SELECT id, title, difficulty, concept, language FROM problems;
    (Service layer strips reference_solution/bug_category before returning
    to the client -- see schemas.problem.ProblemPublic.)
    """
    return db.query(Problem).all()


def create_session(db: DBSession, user_id: int, problem_id: int) -> SessionModel:
    """
    Equivalent SQL:
        INSERT INTO sessions (user_id, problem_id, started_at, solved,
                               highest_hint_level, total_attempts)
        VALUES (:user_id, :problem_id, CURRENT_TIMESTAMP, 0, 0, 0);
    """
    session = SessionModel(user_id=user_id, problem_id=problem_id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: DBSession, session_id: int) -> SessionModel | None:
    """
    Equivalent SQL:
        SELECT * FROM sessions WHERE id = :session_id;
    """
    return db.query(SessionModel).filter(SessionModel.id == session_id).first()


def next_attempt_number(db: DBSession, session_id: int) -> int:
    """
    Equivalent SQL:
        SELECT COALESCE(MAX(attempt_number), 0) + 1
        FROM attempts WHERE session_id = :session_id;
    """
    last = (
        db.query(Attempt)
        .filter(Attempt.session_id == session_id)
        .order_by(Attempt.attempt_number.desc())
        .first()
    )
    return (last.attempt_number + 1) if last else 1


def create_attempt(db: DBSession, **fields) -> Attempt:
    """
    Equivalent SQL:
        INSERT INTO attempts (session_id, attempt_number, language,
            submitted_code, compilation_success, tests_passed, tests_total,
            runtime_error, compiler_error, execution_time_ms, created_at)
        VALUES (...);
    """
    attempt = Attempt(**fields)
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def add_test_results(db: DBSession, attempt_id: int, results: list[dict]) -> None:
    """
    Equivalent SQL (per row):
        INSERT INTO test_results (attempt_id, test_identifier, passed,
            actual_output, error_type, hidden)
        VALUES (:attempt_id, :test_identifier, :passed, :actual_output,
                :error_type, :hidden);
    """
    for r in results:
        db.add(TestResult(attempt_id=attempt_id, **r))
    db.commit()


def get_previous_attempts(db: DBSession, session_id: int, before_attempt_number: int) -> list[Attempt]:
    """
    Equivalent SQL:
        SELECT * FROM attempts
        WHERE session_id = :session_id AND attempt_number < :n
        ORDER BY attempt_number ASC;
    """
    return (
        db.query(Attempt)
        .filter(Attempt.session_id == session_id, Attempt.attempt_number < before_attempt_number)
        .order_by(Attempt.attempt_number.asc())
        .all()
    )


def add_tutor_interaction(db: DBSession, attempt_id: int, hint_level: int, question: str) -> TutorInteraction:
    """
    Equivalent SQL:
        INSERT INTO tutor_interactions (attempt_id, hint_level, tutor_question, created_at)
        VALUES (:attempt_id, :hint_level, :question, CURRENT_TIMESTAMP);
    """
    interaction = TutorInteraction(attempt_id=attempt_id, hint_level=hint_level, tutor_question=question)
    db.add(interaction)
    db.commit()
    db.refresh(interaction)
    return interaction


def upsert_concept_progress(db: DBSession, user_id: int, concept: str, solved: bool, hint_level: int) -> ConceptProgress:
    """
    Equivalent SQL (SQLite upsert):
        INSERT INTO concept_progress (user_id, concept, attempts, solved_count, average_hint_level)
        VALUES (:user_id, :concept, 1, :solved_int, :hint_level)
        ON CONFLICT(user_id, concept) DO UPDATE SET
            attempts = attempts + 1,
            solved_count = solved_count + :solved_int,
            average_hint_level = (average_hint_level * attempts + :hint_level) / (attempts + 1);
    """
    row = (
        db.query(ConceptProgress)
        .filter(ConceptProgress.user_id == user_id, ConceptProgress.concept == concept)
        .first()
    )
    if row is None:
        row = ConceptProgress(
            user_id=user_id, concept=concept, attempts=1,
            solved_count=1 if solved else 0, average_hint_level=float(hint_level),
        )
        db.add(row)
    else:
        new_total = row.attempts + 1
        row.average_hint_level = (row.average_hint_level * row.attempts + hint_level) / new_total
        row.attempts = new_total
        if solved:
            row.solved_count += 1
    db.commit()
    db.refresh(row)
    return row
