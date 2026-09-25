"""
Analysis service: orchestrates the language-specific analyzers into one
bug signal string the tutor prompt can consume. This is the seam between
"raw execution/compiler output" and "something a Socratic prompt can use."
"""

from execution.base_runner import ExecutionResult
from analysis.python_ast_analyzer import analyze as analyze_python_ast
from analysis.cpp_diagnostic_parser import parse as parse_cpp_diagnostics
from analysis.bug_classifier import classify, BugSignal


def analyze_attempt(language: str, code: str, result: ExecutionResult, tests_passed: int, tests_total: int) -> BugSignal:
    static = analyze_python_ast(code) if language == "python" else None

    if language == "cpp" and result.compiler_diagnostics:
        # Parsed for future use (e.g. surfacing structured diagnostics to
        # the frontend); not yet folded into BugSignal beyond compiled=False,
        # which classify() already handles via result.error_type.
        _ = parse_cpp_diagnostics(result.compiler_diagnostics)

    return classify(result, static, tests_passed, tests_total)
