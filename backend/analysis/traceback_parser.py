"""
Python traceback parsing.

python_runner.py already does coarse error classification (syntax vs
runtime) and last-line extraction, because that's cheap and needed
immediately for ExecutionResult. This module is for deeper analysis the
tutor/bug_classifier need: exception type, message, and the chain of frames
-- used to decide *which* Socratic question fits, not just whether one is
needed.
"""

import re
from dataclasses import dataclass

_EXC_LINE_RE = re.compile(r'^(\w+(?:\.\w+)*): (.*)$', re.MULTILINE)
_FRAME_RE = re.compile(r'File "(.+)", line (\d+), in (.+)')


@dataclass
class ParsedTraceback:
    exception_type: str | None
    exception_message: str | None
    frames: list[tuple[str, int, str]]  # (file, line, function)


def parse(stderr: str) -> ParsedTraceback:
    frames = [(f, int(ln), fn) for f, ln, fn in _FRAME_RE.findall(stderr)]
    exc_match = list(_EXC_LINE_RE.finditer(stderr))
    if exc_match:
        last = exc_match[-1]
        return ParsedTraceback(exception_type=last.group(1), exception_message=last.group(2), frames=frames)
    return ParsedTraceback(exception_type=None, exception_message=None, frames=frames)
