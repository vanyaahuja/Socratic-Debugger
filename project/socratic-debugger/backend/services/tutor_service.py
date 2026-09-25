"""
Tutor service: builds the Socratic prompt and validates the LLM's response.

State management: the tutor is given the FULL conversation transcript for
the current attempt on every call, not just the single most recent turn --
see `conversation_history` in build_followup_prompt. Without this the
model has no memory of what the student already correctly identified
earlier and will re-ask a settled question.

Structured response schema: TutorHint carries `response_type` (question /
acknowledgement / instruction / solution) and `reasoning_stage` (where the
student is in the debugging process) alongside the message text, so the
frontend can decide whether to show a reply box without parsing prose, and
so "resolved" is an explicit signal rather than something inferred from
the wording of the message.
"""

import os
import json
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from pydantic import ValidationError

from schemas import TutorHint
import logging
from google.genai import types
logger = logging.getLogger(__name__)

# What the tutor is allowed to do at each hint level. Levels 1-4 must never
# hand over corrected code or name the exact faulty expression; level 5 is
# the only level where near-solution guidance is acceptable.
ALLOWED_AT_LEVEL = {
    1: "Ask a broad question about what the code is supposed to do vs. what it does.",
    2: "Point toward the general area/concept (e.g. 'boundary conditions', 'loop range') without naming a line.",
    3: "Ask the student to trace execution manually for a specific input.",
    4: "Ask a narrowing question that isolates the faulty expression, still without stating the fix.",
    5: "Give the direct correction and briefly explain why the original code fails. Corrected code is allowed at this level."
}

RESPONSE_SHAPE = """Respond with JSON only, matching this exact shape:
{
  "message": "...",
  "response_type": "question" | "acknowledgement" | "instruction" | "solution",
  "reasoning_stage": "identify_bug" | "understand_cause" | "formulate_fix" | "implement_fix" | "reflect" | "resolved",
  "concept": "...",
  "hint_level": <int 1-5>,
  "solution_leakage": false
}

Field guidance:
- response_type "question": you are asking the student something and expect a reply.
- response_type "acknowledgement": confirming/reacting to what they said; may still contain a follow-up question.
- response_type "instruction": telling them what to do next (e.g. "implement that fix and resubmit") -- no reply expected, do not phrase it as a question.
- response_type "solution" is ONLY valid at hint_level 5.
- reasoning_stage should reflect where the student actually is right now, based on the conversation so far -- use "resolved" once they've correctly identified both the cause and the fix, or once all tests pass.
"""

SYSTEM_PROMPT = f"""You are "Socrates," an expert programming tutor (Python and C++) using the Socratic method.

Rules (never break these):
- At hint levels 1-4, do not give the direct answer or corrected code.
- At hint level 5, give the direct correction and briefly explain why it works.
- At hint levels 1-4, ask at most ONE concise Socratic question per turn.
- At hint level 5, you do NOT need to ask a question.
- Never repeat substantially the same question that has already been asked.
- If the student has already identified the root cause correctly, DO NOT ask them to identify it again -- move to reasoning_stage "formulate_fix" or later.
- If the learner has already resolved the current issue (correct cause AND correct fix), use response_type "instruction" or "acknowledgement" with reasoning_stage "resolved", telling them to implement/test the fix -- do not keep interrogating them.
- Do not ask leading questions that reveal the answer.
- If all tests pass, use reasoning_stage "resolved" and ask what the student wants to do next.
- Obey the hint-level ceiling given to you exactly; do not exceed it even if it would be more helpful to.
- Focus only on the current debugging state given to you -- do not invent details about the code you weren't given.

{RESPONSE_SHAPE}
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

Previous tutor message:
{previous_question or "(none yet -- this is the first hint)"}

Student hypothesis:
{student_hypothesis or "(not provided)"}

Student's current code:
```{language}
{code}
```

Respond with exactly one JSON object as specified. No prose outside the JSON.
"""

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise RuntimeError("GEMINI_API_KEY could not be loaded")

client = genai.Client(api_key=api_key)


def _call_llm(prompt: str) -> str:
    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3,
        ),
    )

    return response.text.strip()


def contains_leakage(hint: TutorHint, reference_solution: str) -> bool:
    """
    Simple, deterministic leakage guard per the spec: "perform simple checks
    against reference solution / exact corrected lines / known fixes."
    This does substring overlap on meaningfully long code fragments -- not
    semantic analysis. A more advanced LLM-based evaluator can replace this
    later without changing the calling contract.
    """
    message_lower = hint.message.lower()
    ref_lines = [ln.strip() for ln in reference_solution.splitlines() if len(ln.strip()) > 8]
    return any(line.lower() in message_lower for line in ref_lines)


# Fallback content per hint level -- (message, response_type, reasoning_stage).
# Used to build a full TutorHint when the LLM call fails or its response is
# rejected (exceeds the hint-level ceiling, or leaks the solution below
# level 5). Kept as plain tuples rather than TutorHint literals so they stay
# easy to scan/edit; _build_fallback turns them into real TutorHint objects.
FALLBACK_HINTS = {
    1: ("What is this function supposed to return, and does it always do that?", "question", "identify_bug"),
    2: ("Walk through the code line by line for one input. Where does the value stop matching what you expect?", "question", "identify_bug"),
    3: ("Try adding a print statement right before the point you suspect is wrong. What do you see?", "question", "understand_cause"),
    4: ("Look closely at the boundary values (first/last iteration, first/last index). What happens there?", "question", "understand_cause"),
    5: ("You've identified the general area -- can you explain in your own words why that specific expression is wrong?", "question", "understand_cause"),
}

FOLLOWUP_FALLBACKS = {
    1: ("That's a reasonable starting point -- now try tracing through the function with one concrete example. What happens?", "question", "identify_bug"),
    2: ("Okay -- given that, what do you notice about the very first or very last time through the loop?", "question", "understand_cause"),
    3: ("Good, keep going with that trace. At which exact line does the value stop matching what you'd expect?", "question", "understand_cause"),
    4: ("You're close -- can you say precisely what that expression evaluates to, versus what it should?", "question", "formulate_fix"),
    5: ("You've named the right spot. Why does that specific line produce the wrong result?", "question", "formulate_fix"),
}


def _build_fallback(hint_level: int, bug_category_signal: str, fallback_map: dict) -> TutorHint:
    message, response_type, reasoning_stage = fallback_map.get(hint_level, fallback_map[1])
    return TutorHint(
        message=message,
        response_type=response_type,
        reasoning_stage=reasoning_stage,
        concept=bug_category_signal,
        hint_level=hint_level,
        solution_leakage=False,
    )


def build_followup_prompt(
    *,
    code: str,
    language: str,
    tests_passed: int,
    tests_total: int,
    hint_level: int,
    conversation_history: list[tuple[str, str | None]],
    student_response: str,
) -> str:
    """
    `conversation_history` is the FULL transcript for this attempt so far:
    a list of (tutor_message, student_response) pairs, oldest first.
    `student_response` is the latest answer, not yet in that list.
    """
    hint_rule = ALLOWED_AT_LEVEL.get(hint_level, ALLOWED_AT_LEVEL[1])

    transcript_lines = []
    for message, response in conversation_history:
        transcript_lines.append(f"Tutor: {message}")
        if response:
            transcript_lines.append(f"Student: {response}")
    transcript_lines.append(f"Student: {student_response}")
    transcript = "\n".join(transcript_lines)

    return f"""{SYSTEM_PROMPT}

You are mid-conversation with a student. Below is the FULL conversation so
far for this debugging attempt, oldest first, ending with their latest
response. Read all of it before replying -- do not re-ask something the
student already correctly stated earlier in this transcript.

Conversation so far:
{transcript}

React to the student's LATEST response specifically:
- If their reasoning correctly identifies the root cause (whether just now
  or earlier in this transcript): acknowledge it briefly, referencing what
  they said, and move reasoning_stage to "formulate_fix" or later -- do NOT
  ask them to identify the same cause again.
- If they know the cause but not the fix yet: ask them to formulate the
  fix (reasoning_stage "formulate_fix").
- If they have correctly described both the cause and the fix (whether
  just now or earlier): use reasoning_stage "resolved", response_type
  "instruction" or "acknowledgement", and tell them to implement and test
  it -- stop asking questions.
- At hint level 5: directly explain and show the correction
  (response_type "solution").

Current debugging state:
Language: {language}
Tests: {tests_passed}/{tests_total}
Hint level ceiling (do not exceed): {hint_level}
Allowed at this level: {hint_rule}

Student's current code:
```{language}
{code}
```

Respond with exactly one JSON object as specified. No prose outside the JSON.
"""


def _generate_validated(prompt: str, hint_level: int, bug_category_signal: str,
                         reference_solution: str, fallback_map: dict) -> TutorHint:
    """Shared LLM-call -> parse -> validate -> leakage-check -> fallback
    pipeline, used by both get_hint (fresh hint) and respond_to_reasoning
    (follow-up). Only the prompt and the fallback map differ between them."""
    try:
        raw = _call_llm(prompt)
        data = json.loads(raw)
        hint = TutorHint(**data)
    except Exception:
        logger.warning("LLM call failed, falling back to canned response", exc_info=True)
        return _build_fallback(hint_level, bug_category_signal, fallback_map)

    if hint.hint_level > hint_level:
        return _build_fallback(hint_level, bug_category_signal, fallback_map)

    # response_type "solution" is only legitimate at hint_level 5 -- if the
    # model returns it early, treat it the same as any other leakage.
    leaked = contains_leakage(hint, reference_solution) or (
        hint.response_type == "solution" and hint_level < 5
    )
    if hint_level < 5 and leaked:
        return _build_fallback(hint_level, bug_category_signal, fallback_map)

    return hint


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
    return _generate_validated(prompt, hint_level, bug_category_signal, reference_solution, FALLBACK_HINTS)


def respond_to_reasoning(
    *,
    code: str,
    language: str,
    tests_passed: int,
    tests_total: int,
    hint_level: int,
    conversation_history: list[tuple[str, str | None]],
    student_response: str,
    bug_category_signal: str,
    reference_solution: str,
) -> TutorHint:
    """The other half of an actual conversation: called when the student
    submits their reasoning, so the tutor reacts to it -- with the full
    transcript so far -- instead of just persisting it silently."""
    prompt = build_followup_prompt(
        code=code, language=language, tests_passed=tests_passed, tests_total=tests_total,
        hint_level=hint_level, conversation_history=conversation_history, student_response=student_response,
    )
    return _generate_validated(prompt, hint_level, bug_category_signal, reference_solution, FOLLOWUP_FALLBACKS)
