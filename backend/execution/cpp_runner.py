"""
C++ execution runner.

Two-phase: compile with g++, then (if compilation succeeds) execute the
binary. These are kept as clearly separate steps -- and separately reported
in ExecutionResult -- because "compilation failed" and "compiled but wrong
answer" are pedagogically very different states for the Socratic tutor to
respond to.
"""

import subprocess
import tempfile
import time
from pathlib import Path

from execution.base_runner import BaseRunner, ExecutionResult


class CppRunner(BaseRunner):
    def run(self, code: str, stdin: str = "", timeout_seconds: float = 5.0) -> ExecutionResult:
        with tempfile.TemporaryDirectory() as tmpdir:
            src_path = Path(tmpdir) / "submission.cpp"
            bin_path = Path(tmpdir) / "submission"
            src_path.write_text(code)

            compile_proc = subprocess.run(
                ["g++", "-std=c++17", "-O0", "-o", str(bin_path), str(src_path)],
                capture_output=True,
                text=True,
                timeout=timeout_seconds * 2,  # compilation gets its own, more generous budget
            )

            if compile_proc.returncode != 0:
                return ExecutionResult(
                    language="cpp",
                    compiled=False,
                    success=False,
                    stderr=compile_proc.stderr,
                    error_type="compile_error",
                    error_message="Compilation failed",
                    compiler_diagnostics=compile_proc.stderr,
                    exit_code=compile_proc.returncode,
                )

            start = time.perf_counter()
            try:
                run_proc = subprocess.run(
                    [str(bin_path)],
                    input=stdin,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    cwd=tmpdir,
                )
            except subprocess.TimeoutExpired as e:
                return ExecutionResult(
                    language="cpp",
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

            if run_proc.returncode != 0:
                # Negative returncode on POSIX indicates death by signal
                # (e.g. -11 = SIGSEGV) -- worth surfacing distinctly from a
                # normal nonzero exit, since it usually means memory misuse.
                abnormal = run_proc.returncode < 0
                return ExecutionResult(
                    language="cpp",
                    compiled=True,
                    success=False,
                    stdout=run_proc.stdout,
                    stderr=run_proc.stderr,
                    error_type="runtime_error",
                    error_message=(
                        f"Program terminated by signal {-run_proc.returncode}"
                        if abnormal else f"Exited with code {run_proc.returncode}"
                    ),
                    execution_time_ms=elapsed_ms,
                    exit_code=run_proc.returncode,
                )

            return ExecutionResult(
                language="cpp",
                compiled=True,
                success=True,
                stdout=run_proc.stdout,
                stderr=run_proc.stderr,
                execution_time_ms=elapsed_ms,
                exit_code=run_proc.returncode,
            )
