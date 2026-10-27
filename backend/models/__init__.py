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
    # sha256 of the extension's random profile token (never the token itself).
    token_hash = Column(String(64), nullable=True)

    __table_args__ = (Index("ix_users_token_hash", "token_hash", unique=True),)

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

    # "local" = seeded practice problem with runnable tests; "leetcode" = a
    # problem the extension reported. LeetCode rows store only identity
    # (slug/number/title/url) -- never the statement or any hidden data.
    source = Column(String(20), nullable=False, default="local", server_default="local")
    external_slug = Column(String(200), nullable=True)
    external_id = Column(String(20), nullable=True)
    url = Column(String(300), nullable=True)

    sessions = relationship("Session", back_populates="problem")

    __table_args__ = (
        Index("ix_problems_concept", "concept"),
        Index("ix_problems_source_slug", "source", "external_slug", unique=True),
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
    # READY -> ANALYZING -> HINT_AVAILABLE | REVISION_PENDING -> ANALYZING ... -> SOLVED
    state = Column(String(20), nullable=False, default="READY", server_default="READY")
    state_updated_at = Column(DateTime, nullable=True)

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
    # Extension attempts: what the page reported, and how trustworthy that is.
    verdict = Column(String(24), nullable=True)
    verdict_source = Column(String(16), nullable=True)   # page | user_reported
    code_hash = Column(String(64), nullable=True)
    feedback = Column(Text, nullable=True)               # short snippet only

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


class MistakeObservation(Base):
    """
    One row per (user, problem, session, category, concept) observation.

    This is the single source of truth for BOTH the "My Mistakes" journal and
    the learner profile: recurring patterns are computed from these rows
    (services/progress_service.py::learner_patterns), never stored twice.
    Only a short summary and evidence are kept -- not source code.
    """
    __tablename__ = "mistake_observations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    problem_id = Column(Integer, ForeignKey("problems.id"), nullable=False)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=True)
    fingerprint = Column(String(64), nullable=False)

    category = Column(String(40), nullable=False)
    concept = Column(String(120), nullable=False)
    what_went_wrong = Column(Text, nullable=False)
    why_happened = Column(Text, nullable=False)
    revision_hint = Column(Text, nullable=False)
    is_hypothesis = Column(Boolean, nullable=False, default=True)
    confidence = Column(String(10), nullable=False)       # medium | high (low is never recorded)
    evidence = Column(Text, nullable=False)

    status = Column(String(24), nullable=False, default="unresolved")  # unresolved | fixed_with_guidance | fixed_independently
    reviewed = Column(Boolean, nullable=False, default=False)
    marked_for_revision = Column(Boolean, nullable=False, default=False)
    occurrences = Column(Integer, nullable=False, default=1)
    hint_level_seen = Column(Integer, nullable=False, default=1)

    first_seen = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen = Column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    problem = relationship("Problem")

    __table_args__ = (
        UniqueConstraint("user_id", "fingerprint", name="uq_mistake_user_fingerprint"),
        Index("ix_mistakes_user_category", "user_id", "category"),
    )
