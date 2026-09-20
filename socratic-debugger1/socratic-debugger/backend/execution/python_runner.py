"""
Python execution runner.

Deliberately uses `subprocess.run` against a temp .py file, NOT `exec()`
in-process. exec() would run untrusted student code inside the FastAPI
process itself -- a student's `import os; os.remove(...)` would have full
access to the server. subprocess at least gets process isolation (and is
the stepping stone to Docker isolation later, per the spec).
"""

import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from execution.base_runner import BaseRunner, ExecutionResult

# Matches the last "File "...", line N" in a traceback to recover the
# failing line number without re-parsing the whole traceback structure here
# (full parsing belongs in analysis/traceback_parser.py).
_LINE_RE = re.compile(r'File ".*", line (\d+)')


class PythonRunner(BaseRunner):
    def run(self, code: str, stdin: str = "", timeout_seconds: float = 5.0) -> ExecutionResult:
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "submission.py"
            script_path.write_text(code)

            start = time.perf_counter()
            try:
                proc = subprocess.run(
                    [sys.executable, str(script_path)],
                    input=stdin,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    cwd=tmpdir,
                )
            except subprocess.TimeoutExpired as e:
                return ExecutionResult(
                    language="python",
                    compiled=True,
                    success=False,
                    stdout=e.stdout or "",
                    stderr=e.stderr or "",
                    error_type="timeout",
                    error_message=f"Execution exceeded {timeout_seconds}s",
                    timed_out=True,
                    execution_time_ms=timeout_seconds * 1000,
                )
            elapsed_ms = (time.perf_counter() - start) * 1000

            if proc.returncode != 0:
                error_type, error_message = self._classify_error(proc.stderr)
                failing_line = self._extract_failing_line(proc.stderr)
                return ExecutionResult(
                    language="python",
                    compiled=True,
                    success=False,
                    stdout=proc.stdout,
                    stderr=proc.stderr,
                    error_type=error_type,
                    error_message=error_message,
                    traceback=proc.stderr,
                    failing_line=failing_line,
                    execution_time_ms=elapsed_ms,
                    exit_code=proc.returncode,
                )

            return ExecutionResult(
                language="python",
                compiled=True,
                success=True,
                stdout=proc.stdout,
                stderr=proc.stderr,
                execution_time_ms=elapsed_ms,
                exit_code=proc.returncode,
            )

    @staticmethod
    def _classify_error(stderr: str) -> tuple[str, str]:
        """Coarse classification -- fine-grained bug typing belongs in
        analysis/bug_classifier.py, which sees this output plus AST info."""
        last_line = stderr.strip().splitlines()[-1] if stderr.strip() else ""
        if "SyntaxError" in stderr:
            return "syntax_error", last_line
        return "runtime_error", last_line

    @staticmethod
    def _extract_failing_line(stderr: str) -> int | None:
        matches = _LINE_RE.findall(stderr)
        return int(matches[-1]) if matches else None
