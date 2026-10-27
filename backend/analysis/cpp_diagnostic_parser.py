"""
C++ compiler diagnostic parsing.

g++ output format (roughly): `file:line:col: error: message`. This parses
that into structured diagnostics so the bug_classifier and tutor prompt
builder don't have to regex g++ output themselves.
"""

import re
from dataclasses import dataclass

_DIAG_RE = re.compile(r'([^:\n]+):(\d+):(\d+):\s*(error|warning|note):\s*(.*)')


@dataclass
class Diagnostic:
    file: str
    line: int
    column: int
    severity: str  # "error" | "warning" | "note"
    message: str


def parse(compiler_output: str) -> list[Diagnostic]:
    return [
        Diagnostic(file=f, line=int(ln), column=int(col), severity=sev, message=msg)
        for f, ln, col, sev, msg in _DIAG_RE.findall(compiler_output)
    ]
