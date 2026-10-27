"""
Pydantic request/response schemas.

Key design rule from the spec: the student must never see reference_solution,
hidden test inputs, exact bug location, bug_category, or the known fix.
ProblemPublic below is the enforcement point -- it's a strict allow-list,
not the ORM model with fields hidden. If someone adds a field to the
Problem model later, it does NOT leak to the client unless someone
deliberately adds it here too.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field


def _cut(n: int):
    """Truncate overlong model output instead of rejecting the whole response."""
    return BeforeValidator(lambda v: v.strip()[:n] if isinstance(v, str) else v)


Text120 = Annotated[str, _cut(120), Field(min_length=1)]
Text300 = Annotated[str, _cut(300), Field(min_length=1)]
Text400 = Annotated[str, _cut(400), Field(min_length=1)]

ErrorCategory = Literal[
    "logic_error", "edge_case", "boundary_indexing", "wrong_algorithm",
    "complexity", "implementation_bug", "problem_interpretation", "other",
]
Verdict = Literal[
    "accepted", "run_passed", "wrong_answer", "runtime_error", "compile_error",
    "time_limit_exceeded", "memory_limit_exceeded", "running", "unknown",
]
FAILED_VERDICTS = {"wrong_answer", "runtime_error", "compile_error",
                   "time_limit_exceeded", "memory_limit_exceeded"}


class Diagnosis(BaseModel):
    """Structured, falsifiable diagnosis. Observed facts and the hypothesis are
    separate fields on purpose: the UI and the journal never present a guess
    as a fact."""
    observed: Text400
    hypothesis: Text400
    confidence: Literal["low", "medium", "high"]
    error_category: ErrorCategory
    concept: Text120
    what_went_wrong: Text300
    revision_hint: Text400


class ProblemPublic(BaseModel):
    """What the student's browser is allowed to see. Notably absent:
    reference_solution, bug_category, hidden tests."""
    id: int
    title: str
    description: str
    difficulty: str
    concept: str
    language: str
    starter_code: str

    class Config:
        from_attributes = True


class SessionCreate(BaseModel):
    user_id: int
    problem_id: int


class SessionOut(BaseModel):
    id: int
    user_id: int
    problem_id: int
    solved: bool
    highest_hint_level: int
    total_attempts: int

    class Config:
        from_attributes = True


class RunRequest(BaseModel):
    session_id: int
    language: str
    code: str


class RunResult(BaseModel):
    """Result of a Run (not Submit) -- experimentation only, not persisted
    as an attempt. Never includes hidden test outcomes."""
    success: bool
    stdout: str
    stderr: str
    error_type: str | None = None
    error_message: str | None = None
    visible_tests_passed: int | None = None
    visible_tests_total: int | None = None
    execution_time_ms: float


class SubmitAttemptRequest(BaseModel):
    session_id: int
    language: str
    code: str


class TestResultPublic(BaseModel):
    test_identifier: str
    passed: bool
    hidden: bool
    # actual_output intentionally omitted for hidden tests at the service
    # layer, not here -- see services/test_service.py::to_public_results


class SubmitAttemptResponse(BaseModel):
    attempt_id: int
    attempt_number: int
    compiled: bool | None
    tests_passed: int
    tests_total: int
    test_results: list[TestResultPublic]
    compiler_error: str | None = None
    runtime_error: str | None = None
    solved: bool


class HintRequest(BaseModel):
    attempt_id: int


class TutorHint(BaseModel):
    message: str

    # Lets the frontend distinguish "still asking something" from "nothing
    # left to respond to" without parsing message text. "solution" is only
    # ever valid at hint_level 5, enforced in tutor_service, not here.
    response_type: Literal[
        "question",       # expects a student reply -- show the Respond box
        "acknowledgement",  # confirms something the student said, may still ask a follow-up
        "instruction",    # e.g. "go implement that fix and resubmit" -- no reply expected
        "solution",       # level 5 only: direct correction given
    ]

    # Where the student is in the debugging process, per this turn's
    # judgment. Exists so the tutor (and the frontend) can tell "resolved"
    # apart from "still working on it" without re-deriving it from prose.
    reasoning_stage: Literal[
        "identify_bug",
        "understand_cause",
        "formulate_fix",
        "implement_fix",
        "reflect",
        "resolved",
    ]

    concept: str
    hint_level: int = Field(ge=1, le=5)
    solution_leakage: bool = False
    # Only populated by the LeetCode flow; old routes leave it None.
    diagnosis: Diagnosis | None = None


class ReasoningSubmit(BaseModel):
    attempt_id: int
    student_response: str


class ProgressOut(BaseModel):
    concept: str
    attempts: int
    solved_count: int
    average_hint_level: float

    class Config:
        from_attributes = True


# --------------------------------------------------------------------------
# Chrome-extension API (api/leetcode.py). Every field is size-capped: page
# content is untrusted and we also transmit as little as possible.
# --------------------------------------------------------------------------

class ProblemContext(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9-]{1,120}$")
    title: str | None = Field(default=None, max_length=200)
    frontend_id: str | None = Field(default=None, max_length=10)
    url: str | None = Field(default=None, max_length=300)
    difficulty: str | None = Field(default=None, max_length=20)
    statement: str = Field(default="", max_length=8000)


class SubmissionContext(BaseModel):
    status: Verdict = "unknown"
    # page = read from the LeetCode UI; user_reported = the student said so.
    source: Literal["page", "user_reported", "none"] = "none"
    # A "Run" on sample cases is not a submission; only kind=submit can solve.
    kind: Literal["submit", "run", "none"] = "none"
    message: str | None = Field(default=None, max_length=2000)
    testcases_passed: int | None = Field(default=None, ge=0, le=100000)
    testcases_total: int | None = Field(default=None, ge=0, le=100000)


class AnalyzeRequest(BaseModel):
    problem: ProblemContext
    language: str = Field(min_length=1, max_length=40)
    code: str = Field(max_length=20000)
    submission: SubmissionContext = Field(default_factory=SubmissionContext)
    session_id: int | None = None
    request_explanation: bool = False
    missing_context: list[Annotated[str, Field(max_length=60)]] = Field(default_factory=list, max_length=20)


class ReplyRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    # Statements are not stored on the server, so the extension re-sends it.
    statement: str = Field(default="", max_length=8000)


class ExplainRequest(BaseModel):
    mode: Literal["hint", "practice"] = "hint"


class MistakePatch(BaseModel):
    reviewed: bool | None = None
    marked_for_revision: bool | None = None


class AnalyzeResponse(BaseModel):
    session_id: int
    attempt_id: int
    attempt_number: int
    state: str
    hint_level: int
    tutor: TutorHint
    solved: bool
    # verified_accepted: Accepted observed on a real submission on the page.
    # unverified_user_report: student says it works; NOT marked solved.
    verification: Literal["verified_accepted", "unverified_user_report", "not_accepted", "pending"]
    mistake_recorded: bool
    mistake_id: int | None = None
    mistake_note: str | None = None
    duplicate_attempt: bool = False


class TranscriptMessage(BaseModel):
    sender: Literal["tutor", "student"]
    text: str
    response_type: str | None = None
    reasoning_stage: str | None = None


class SessionView(BaseModel):
    session_id: int
    state: str
    solved: bool
    highest_hint_level: int
    problem_slug: str | None
    messages: list[TranscriptMessage]


class MistakeOut(BaseModel):
    id: int
    problem_title: str
    problem_slug: str | None
    problem_number: str | None
    problem_url: str | None
    category: str
    concept: str
    what_went_wrong: str
    why_happened: str
    revision_hint: str
    is_hypothesis: bool
    confidence: str
    evidence: str
    status: str
    reviewed: bool
    marked_for_revision: bool
    occurrences: int
    first_seen: datetime
    last_seen: datetime
    resolved_at: datetime | None


class RevisionReply(BaseModel):
    message: str
    mode: Literal["hint", "practice"]
    used_ai: bool
