"""
Tutor service: builds the Socratic prompt and validates the LLM's response.

Lineage from your original evaluation_script.py: the core rules
("never give the direct answer", "ask ONE open-ended question", "don't ask
leading questions", "if the code is correct, say so plainly") are carried
over verbatim in spirit. What's new:

  1. The prompt is now built from structured attempt state (test results,
     hint level, previous question, student's own hypothesis) instead of
     just raw code -- this is what "execution-aware" means.
  2. Output is now structured JSON validated by Pydantic (TutorHint),
     replacing the old `.split('[/INST]')[-1].strip()` string surgery.
  3. Hint-level rules gate what the tutor is allowed to reveal (see
     ALLOWED_AT_LEVEL below) and a leakage check runs on every response.

This module calls out to an LLM API (see `_call_llm`, currently a stub --
wire up your provider's client here). It intentionally does NOT know about
FastAPI, SQLAlchemy, or HTTP -- it takes plain data in, returns a
validated TutorHint out.
"""

import json

from pydantic import ValidationError
from schemas import TutorHint

# What the tutor is allowed to do at each hint level. Levels 1-4 must never
# hand over corrected code or name the exact faulty expression; level 5 is
# the only level where near-solution guidance is acceptable.
ALLOWED_AT_LEVEL = {
    1: "Ask a broad question about what the code is supposed to do vs. what it does.",
    2: "Point toward the general area/concept (e.g. 'boundary conditions', 'loop range') without naming a line.",
    3: "Ask the student to trace execution manually for a specific input.",
    4: "Ask a narrowing question that isolates the faulty expression, still without stating the fix.",
    5: "May confirm the specific line is wrong and ask the student to justify the correct behavior, but must not hand over corrected code outright.",
}

SYSTEM_PROMPT = """You are "Socrates," an expert programming tutor (Python and C++) using the Socratic method.

Rules (never break these):
- NEVER give the direct answer or corrected code, except as allowed at hint level 5.
- Ask exactly ONE concise, open-ended question per turn.
- Do not ask leading questions that reveal the answer.
- If all tests pass, respond that the code looks correct and ask what the student wants to do next.
- Obey the hint-level ceiling given to you exactly; do not exceed it even if it would be more helpful to.
- Focus only on the current debugging state given to you -- do not invent details about the code you weren't given.
- Respond with JSON only, matching this shape:
  {"question": "...", "concept": "...", "hint_level": <int>, "solution_leakage": false}
"""


def build_prompt(
    *,
    code: str,
    language: str,
    tests_passed: int,
    tests_total: int,
    compiled: bool | None,
    bug_category_signal: str,
    hint_level: int,
    previous_question: str | None,
    student_hypothesis: str | None,
) -> str:
    hint_rule = ALLOWED_AT_LEVEL.get(hint_level, ALLOWED_AT_LEVEL[1])
    return f"""{SYSTEM_PROMPT}

Current debugging state:
Language: {language}
Tests: {tests_passed}/{tests_total}
Compiler: {"successful" if compiled else "failed" if compiled is not None else "n/a"}
Static/runtime finding: {bug_category_signal}
Hint level: {hint_level}
Allowed at this level: {hint_rule}

Previous tutor question:
{previous_question or "(none yet -- this is the first hint)"}

Student hypothesis:
{student_hypothesis or "(not provided)"}

Student's current code:
```{language}
{code}
```

Respond with exactly one JSON object as specified. No prose outside the JSON.
"""


def _call_llm(prompt: str) -> str:
    """
    Stub -- wire up your actual LLM API client here (Anthropic, OpenAI,
    etc.). Kept as a separate function so tutor_service is trivially
    testable by monkeypatching this one call.
    """
    raise NotImplementedError("Wire up an LLM API client here.")


def contains_leakage(hint: TutorHint, reference_solution: str) -> bool:
    """
    Simple, deterministic leakage guard per the spec: "perform simple checks
    against reference solution / exact corrected lines / known fixes."
    This does substring overlap on meaningfully long code fragments -- not
    semantic analysis. A more advanced LLM-based evaluator can replace this
    later without changing the calling contract.
    """
    question_lower = hint.question.lower()
    ref_lines = [ln.strip() for ln in reference_solution.splitlines() if len(ln.strip()) > 8]
    return any(line.lower() in question_lower for line in ref_lines)


FALLBACK_HINTS = {
    1: "What is this function supposed to return, and does it always do that?",
    2: "Walk through the code line by line for one input. Where does the value stop matching what you expect?",
    3: "Try adding a print statement right before the point you suspect is wrong. What do you see?",
    4: "Look closely at the boundary values (first/last iteration, first/last index). What happens there?",
    5: "You've identified the general area -- can you explain in your own words why that specific expression is wrong?",
}


def get_hint(
    *,
    code: str,
    language: str,
    tests_passed: int,
    tests_total: int,
    compiled: bool | None,
    bug_category_signal: str,
    hint_level: int,
    previous_question: str | None,
    student_hypothesis: str | None,
    reference_solution: str,
) -> TutorHint:
    prompt = build_prompt(
        code=code, language=language, tests_passed=tests_passed, tests_total=tests_total,
        compiled=compiled, bug_category_signal=bug_category_signal, hint_level=hint_level,
        previous_question=previous_question, student_hypothesis=student_hypothesis,
    )

    try:
        raw = _call_llm(prompt)
        data = json.loads(raw)
        hint = TutorHint(**data)
    except (NotImplementedError, json.JSONDecodeError, ValidationError):
        # Fall back to a predefined safe hint rather than surfacing a
        # malformed/unvalidated response to the student.
        return TutorHint(
            question=FALLBACK_HINTS.get(hint_level, FALLBACK_HINTS[1]),
            concept=bug_category_signal,
            hint_level=hint_level,
            solution_leakage=False,
        )

    if hint.hint_level > hint_level or contains_leakage(hint, reference_solution):
        return TutorHint(
            question=FALLBACK_HINTS.get(hint_level, FALLBACK_HINTS[1]),
            concept=hint.concept,
            hint_level=hint_level,
            solution_leakage=False,
        )

    return hint
