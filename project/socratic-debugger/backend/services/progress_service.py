"""
Progress service: decides the hint level for the *next* hint, and updates
per-concept aggregate stats.

Escalation rule (from the spec's expected-final-experience example):
if tests_passed improved since the previous attempt, do NOT escalate the
hint level even if the student is still failing -- they're making progress
and a bigger hint would short-circuit that. Only escalate when the student
is stuck (no improvement, or a regression) across attempts.
"""

from database.repositories import get_previous_attempts, upsert_concept_progress
from sqlalchemy.orm import Session as DBSession


def determine_hint_level(db: DBSession, session_id: int, current_attempt_number: int,
                          current_tests_passed: int, current_highest_hint_level: int) -> int:
    previous = get_previous_attempts(db, session_id, current_attempt_number)

    if not previous:
        return 1  # first attempt ever -> start at the gentlest hint

    last = previous[-1]
    improved = current_tests_passed > last.tests_passed
    regressed = current_tests_passed < last.tests_passed

    if improved:
        # Progress is being made -- hold at (or even ease back from) the
        # current level rather than escalating.
        return current_highest_hint_level or 1

    if regressed or current_tests_passed == last.tests_passed:
        # Stuck or backsliding -- escalate, capped at 5.
        return min(current_highest_hint_level + 1, 5)

    return current_highest_hint_level or 1


def record_outcome(db: DBSession, user_id: int, concept: str, solved: bool, hint_level: int) -> None:
    upsert_concept_progress(db, user_id=user_id, concept=concept, solved=solved, hint_level=hint_level)
