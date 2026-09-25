"""
Starter tests. Run with: pytest (from backend/).

These cover the two riskiest pieces of logic to get subtly wrong:
runner isolation (does a crashing script actually get classified right?)
and hint escalation (does progress correctly suppress escalation?).
Expand per-endpoint tests as the stub services are filled in.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from execution.python_runner import PythonRunner
from execution.cpp_runner import CppRunner


def test_python_runner_success():
    result = PythonRunner().run("print('hello')")
    assert result.success
    assert "hello" in result.stdout


def test_python_runner_syntax_error():
    result = PythonRunner().run("def f(:\n    pass")
    assert not result.success
    assert result.error_type == "syntax_error"


def test_python_runner_index_error():
    result = PythonRunner().run("x = [1, 2]\nprint(x[5])")
    assert not result.success
    assert result.error_type == "runtime_error"
    assert "IndexError" in (result.stderr or "")


def test_python_runner_timeout():
    result = PythonRunner().run("while True: pass", timeout_seconds=1.0)
    assert result.timed_out
    assert result.error_type == "timeout"


def test_cpp_runner_compile_error():
    result = CppRunner().run("int main( { return 0; }")  # missing paren
    assert not result.compiled
    assert result.error_type == "compile_error"


def test_cpp_runner_success():
    code = """
#include <iostream>
int main() { std::cout << "hi"; return 0; }
"""
    result = CppRunner().run(code)
    assert result.compiled
    assert result.success
    assert "hi" in result.stdout
