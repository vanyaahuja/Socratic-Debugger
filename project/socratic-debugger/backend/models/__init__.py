"""
SQLAlchemy ORM models.

Design notes (why each relationship exists):

- Problem 1--* Session: a user can attempt the same problem across multiple
  sessions (e.g. retrying weeks later), so sessions reference problem_id
  rather than problems owning a fixed user.
- Session 1--* Attempt: every Submit Attempt creates a row here. attempt_number
  is denormalized (redundant with COUNT) purely so the frontend can display
  "Attempt 3" without a join+count query on every request.
- Attempt 1--* TestResult: one row per test case per attempt, so we can show
  "4/6 passed" AND drill into which specific test failed, without re-running
  anything.
- Attempt 1--* TutorInteraction: a hint can be requested multiple times per
  attempt (student asks, tutor answers, student responds with reasoning),
  so this is 1-to-many, not 1-to-1.
- User 1--* ConceptProgress: aggregated per (user, concept) so the progress
  endpoint doesn't have to scan every attempt/session on every page load.

Equivalent raw SQL for the core join (get a user's attempts with problem info):

    SELECT a.*, p.title, p.concept
    FROM attempts a
    JOIN sessions s ON a.session_id = s.id
    JOIN problems p ON s.problem_id = p.id
    WHERE s.user_id = :user_id
    ORDER BY a.created_at DESC;

SQLAlchemy expresses this as session.problem and session.attempts
relationship traversals instead of manual joins -- but the SQL above is
exactly what gets generated.
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey, DateTime, Text, Float,
    UniqueConstraint, Index, JSON,
)
from sqlalchemy.orm import relationship
from database.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    sessions = relationship("Session", back_populates="user")
    concept_progress = relationship("ConceptProgress", back_populates="user")


class Problem(Base):
    __tablename__ = "problems"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    difficulty = Column(String(20), nullable=False)  # e.g. "easy" | "medium" | "hard"
    concept = Column(String(80), nullable=False)      # e.g. "binary search"
    bug_category = Column(String(80), nullable=False)  # internal only, never sent to client
    language = Column(String(10), nullable=False)  # "python" | "cpp"

    starter_code = Column(Text, nullable=False)
    reference_solution = Column(Text, nullable=False)  # NEVER serialized to student-facing schemas
    # JSON shape: {"visible": [{"id","stdin","expected_stdout"}, ...],
    #              "hidden":  [{"id","stdin","expected_stdout"}, ...]}
    # SQLite stores this as TEXT under the hood; Postgres would use its
    # native JSONB -- SQLAlchemy's JSON type abstracts that difference away.
    tests = Column(JSON, nullable=False, default=dict)

    sessions = relationship("Session", back_populates="problem")

    __table_args__ = (
        Index("ix_problems_concept", "concept"),
    )


class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    problem_id = Column(Integer, ForeignKey("problems.id"), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    solved = Column(Boolean, default=False, nullable=False)
    highest_hint_level = Column(Integer, default=0, nullable=False)
    total_attempts = Column(Integer, default=0, nullable=False)

    user = relationship("User", back_populates="sessions")
    problem = relationship("Problem", back_populates="sessions")
    attempts = relationship("Attempt", back_populates="session", order_by="Attempt.attempt_number")

    __table_args__ = (
        Index("ix_sessions_user_problem", "user_id", "problem_id"),
    )


class Attempt(Base):
    __tablename__ = "attempts"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    attempt_number = Column(Integer, nullable=False)  # denormalized, see module docstring
    language = Column(String(10), nullable=False)
    submitted_code = Column(Text, nullable=False)
    compilation_success = Column(Boolean, nullable=True)  # null for Python (no compile step)
    tests_passed = Column(Integer, default=0, nullable=False)
    tests_total = Column(Integer, default=0, nullable=False)
    runtime_error = Column(Text, nullable=True)
    compiler_error = Column(Text, nullable=True)
    execution_time_ms = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("Session", back_populates="attempts")
    test_results = relationship("TestResult", back_populates="attempt")
    tutor_interactions = relationship("TutorInteraction", back_populates="attempt")

    __table_args__ = (
        UniqueConstraint("session_id", "attempt_number", name="uq_session_attempt_number"),
    )


class TestResult(Base):
    __tablename__ = "test_results"

    id = Column(Integer, primary_key=True)
    attempt_id = Column(Integer, ForeignKey("attempts.id"), nullable=False)
    test_identifier = Column(String(80), nullable=False)  # e.g. "visible_1", "hidden_3"
    passed = Column(Boolean, nullable=False)
    actual_output = Column(Text, nullable=True)
    error_type = Column(String(50), nullable=True)  # "assertion_failed" | "exception" | "timeout" | None
    hidden = Column(Boolean, default=False, nullable=False)

    attempt = relationship("Attempt", back_populates="test_results")


class TutorInteraction(Base):
    __tablename__ = "tutor_interactions"

    id = Column(Integer, primary_key=True)
    attempt_id = Column(Integer, ForeignKey("attempts.id"), nullable=False)
    hint_level = Column(Integer, nullable=False)
    tutor_question = Column(Text, nullable=False)
    student_response = Column(Text, nullable=True)  # filled in later via /reasoning endpoint
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    attempt = relationship("Attempt", back_populates="tutor_interactions")


class ConceptProgress(Base):
    __tablename__ = "concept_progress"

    # composite PK: one row per (user, concept) -- this is an aggregate/rollup
    # table, recomputed incrementally as attempts land, not a raw log.
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    concept = Column(String(80), primary_key=True)
    attempts = Column(Integer, default=0, nullable=False)
    solved_count = Column(Integer, default=0, nullable=False)
    average_hint_level = Column(Float, default=0.0, nullable=False)

    user = relationship("User", back_populates="concept_progress")
