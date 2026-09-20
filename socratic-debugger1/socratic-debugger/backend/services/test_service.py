"""
Test service: runs a problem's test cases against submitted code and
produces structured pass/fail results.

Test case format expected on a Problem (stored as JSON in a real DB column
-- represented here as a plain dict for the stub; wire up a JSON column or
a separate `problem_tests` table when implementing):

    {
        "visible": [{"id": "visible_1", "stdin": "...", "expected_stdout": "..."}],
        "hidden":  [{"id": "hidden_1",  "stdin": "...", "expected_stdout": "..."}],
    }

Design note: this module is the ONLY place that sees expected_stdout for
hidden tests. Everything it returns to callers has already dropped that
information for hidden entries -- callers (API layer, tutor service) never
get a chance to accidentally leak it.
"""

from dataclasses import dataclass

from services.execution_service import execute


@dataclass
class TestOutcome:
    test_identifier: str
    passed: bool
    hidden: bool
    actual_output: str | None
    error_type: str | None


def run_tests(language: str, code: str, tests: dict) -> list[TestOutcome]:
    outcomes: list[TestOutcome] = []
    all_tests = [
        (*_as_tuple(t), False) for t in tests.get("visible", [])
    ] + [
        (*_as_tuple(t), True) for t in tests.get("hidden", [])
    ]

    for test_id, stdin, expected, hidden in all_tests:
        result = execute(language, code, stdin=stdin)
        if not result.success:
            outcomes.append(TestOutcome(
                test_identifier=test_id, passed=False, hidden=hidden,
                actual_output=result.stdout, error_type=result.error_type,
            ))
            continue

        actual = result.stdout.strip()
        passed = actual == expected.strip()
        outcomes.append(TestOutcome(
            test_identifier=test_id, passed=passed, hidden=hidden,
            actual_output=actual, error_type=None if passed else "assertion_failed",
        ))
    return outcomes


def _as_tuple(t: dict) -> tuple[str, str, str]:
    return t["id"], t.get("stdin", ""), t.get("expected_stdout", "")


def to_public_results(outcomes: list[TestOutcome]) -> list[dict]:
    """Strip actual_output/error_type for hidden tests before this ever
    reaches an API response -- the frontend should only ever see pass/fail
    for hidden tests, never why."""
    public = []
    for o in outcomes:
        entry = {"test_identifier": o.test_identifier, "passed": o.passed, "hidden": o.hidden}
        public.append(entry)
    return public


def summarize(outcomes: list[TestOutcome]) -> tuple[int, int]:
    passed = sum(1 for o in outcomes if o.passed)
    return passed, len(outcomes)
