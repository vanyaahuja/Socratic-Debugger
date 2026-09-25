"""
Combines ExecutionResult + static analysis findings into a coarse bug
category label used ONLY to steer the Socratic prompt (e.g. "hint at
boundary conditions, not at exceptions"). This is deliberately coarse --
it is not trying to pinpoint the exact bug, since that's the tutor's job
to elicit from the student, not the system's job to announce.
"""

from dataclasses import dataclass

from execution.base_runner import ExecutionResult
from analysis.python_ast_analyzer import StaticFindings


@dataclass
class BugSignal:
    category: str          # e.g. "boundary_condition", "mutation_error", "exception", "logic_error", "none"
    confidence: str        # "low" | "medium" | "high"


def classify(result: ExecutionResult, static: StaticFindings | None, tests_passed: int, tests_total: int) -> BugSignal:
    if static and static.parse_error:
        return BugSignal(category="syntax_error", confidence="high")

    if static and static.mutates_list_while_iterating:
        return BugSignal(category="mutation_error", confidence="medium")

    if static and static.uses_range_len_plus_offset:
        return BugSignal(category="boundary_condition", confidence="medium")

    if result.error_type == "runtime_error" and result.error_message and "index" in result.error_message.lower():
        return BugSignal(category="boundary_condition", confidence="medium")

    if result.success and 0 < tests_passed < tests_total:
        return BugSignal(category="logic_error", confidence="low")

    if tests_total > 0 and tests_passed == tests_total:
        return BugSignal(category="none", confidence="high")

    return BugSignal(category="unknown", confidence="low")
