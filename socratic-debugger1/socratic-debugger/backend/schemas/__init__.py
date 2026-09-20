"""
Pydantic request/response schemas.

Key design rule from the spec: the student must never see reference_solution,
hidden test inputs, exact bug location, bug_category, or the known fix.
ProblemPublic below is the enforcement point -- it's a strict allow-list,
not the ORM model with fields hidden. If someone adds a field to the
Problem model later, it does NOT leak to the client unless someone
deliberately adds it here too.
"""

from pydantic import BaseModel, Field


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
    question: str
    concept: str
    hint_level: int = Field(ge=1, le=5)
    solution_leakage: bool = False


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
