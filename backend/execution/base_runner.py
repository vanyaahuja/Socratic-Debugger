"""
Language-independent execution interface.

Why this exists: the spec explicitly forbids mixing Python and C++ execution
logic into one function. This module defines the *shape* every runner must
produce (ExecutionResult) so that everything downstream -- test comparison,
analysis, the tutor prompt builder -- consumes one structure regardless of
which language ran.

Trade-off: this means python_runner.py and cpp_runner.py duplicate some
plumbing (temp file creation, subprocess timeout handling). That's
intentional per the spec's "do not mix" rule -- the alternative (one
runner with if/else branches for language) is exactly what we're avoiding,
because it grows unmanageable once you add a third language.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ExecutionResult:
    language: str                      # "python" | "cpp"
    compiled: bool                     # always True for python (no compile step)
    success: bool                      # program ran to completion without error
    stdout: str = ""
    stderr: str = ""
    error_type: str | None = None      # "syntax_error" | "runtime_error" | "compile_error" | "timeout" | None
    error_message: str | None = None
    traceback: str | None = None       # python-specific
    compiler_diagnostics: str | None = None  # cpp-specific
    failing_line: int | None = None
    execution_time_ms: float = 0.0
    exit_code: int | None = None
    timed_out: bool = False


class BaseRunner(ABC):
    """
    Every language runner must implement `run`, which takes source code and
    a timeout, and returns a fully-populated ExecutionResult. Runners own
    their own temp-file lifecycle (create in run(), clean up in a finally
    block) -- callers never touch the filesystem directly.
    """

    @abstractmethod
    def run(self, code: str, stdin: str = "", timeout_seconds: float = 5.0) -> ExecutionResult:
        ...
