"""
Execution service: the single place that maps a `language` string to a
runner. This is the one intentional if/else on language in the whole
codebase -- everything else consumes ExecutionResult, which is
language-agnostic.
"""

from execution.base_runner import ExecutionResult
from execution.python_runner import PythonRunner
from execution.cpp_runner import CppRunner

_RUNNERS = {
    "python": PythonRunner(),
    "cpp": CppRunner(),
}


def execute(language: str, code: str, stdin: str = "", timeout_seconds: float = 5.0) -> ExecutionResult:
    runner = _RUNNERS.get(language)
    if runner is None:
        raise ValueError(f"Unsupported language: {language}")
    return runner.run(code, stdin=stdin, timeout_seconds=timeout_seconds)
