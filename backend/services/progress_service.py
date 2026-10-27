"""
Progress service: decides the hint level for the *next* hint, and updates
per-concept aggregate stats.

Escalation rule (from the spec's expected-final-experience example):
if tests_passed improved since the previous attempt, do NOT escalate the
hint level even if the student is still failing -- they're making progress
and a bigger hint would short-circuit that. Only escalate when the student
is stuck (no improvement, or a regression) across attempts.
"""

from database.repositories import get_previous_attempts, upsert_concept_progress
from sqlalchemy.orm import Session as DBSession


def determine_hint_level(db: DBSession, session_id: int, current_attempt_number: int,
                          current_tests_passed: int, current_highest_hint_level: int) -> int:
    previous = get_previous_attempts(db, session_id, current_attempt_number)

    if not previous:
        return 1  # first attempt ever -> start at the gentlest hint

    last = previous[-1]
    improved = current_tests_passed > last.tests_passed
    regressed = current_tests_passed < last.tests_passed

    if improved:
        # Progress is being made -- hold at (or even ease back from) the
        # current level rather than escalating.
        return current_highest_hint_level or 1

    if regressed or current_tests_passed == last.tests_passed:
        # Stuck or backsliding -- escalate, capped at 5.
        return min(current_highest_hint_level + 1, 5)

    return current_highest_hint_level or 1


def record_outcome(db: DBSession, user_id: int, concept: str, solved: bool, hint_level: int) -> None:
    upsert_concept_progress(db, user_id=user_id, concept=concept, solved=solved, hint_level=hint_level)


# ==========================================================================
# LeetCode extension: hint ladder, mistake journal, learner patterns.
#
# Everything below is rule-based and inspectable (no ML). The journal and the
# learner profile are two views of the same MistakeObservation rows.
# ==========================================================================

import hashlib
from collections import defaultdict
from datetime import datetime, timedelta

from models import MistakeObservation, Problem
from schemas import Diagnosis, FAILED_VERDICTS

# Higher = closer to correct. A compile error -> runtime error -> wrong answer
# -> TLE -> Accepted progression counts as progress even without test counts.
_VERDICT_RANK = {"compile_error": 0, "runtime_error": 1, "wrong_answer": 2,
                 "memory_limit_exceeded": 3, "time_limit_exceeded": 3, "accepted": 5}


def leetcode_hint_level(*, verdict: str, highest: int, previous, code_changed: bool,
                        passed: int | None, total: int | None, request_explanation: bool,
                        escalate: bool) -> int:
    """
    Progressive ladder (1 conceptual probe ... 4 detailed explanation; 5 is the
    transfer check and is ONLY reachable via a verified Accepted).
    - Replies inside an ongoing conversation never escalate (escalate=False).
    - Explicit request for an explanation jumps to level 4.
    - Same code asked about again -> the student is stuck -> +1.
    - Revised code that improved -> hold the level (don't over-help).
    - Revised code that did not improve -> +1.
    """
    if verdict == "accepted":
        return 5
    if request_explanation:
        return max(highest, 4)
    if not escalate:
        return max(highest, 1)
    if previous is None or highest == 0:
        return 1
    if not code_changed:
        return min(highest + 1, 4)
    prev_rank = _VERDICT_RANK.get(previous.verdict or "", -1)
    improved = _VERDICT_RANK.get(verdict, -1) > prev_rank
    if (not improved and passed is not None and total
            and previous.tests_total and previous.tests_total == total):
        improved = passed > previous.tests_passed
    return min(max(highest, 1), 4) if improved else min(highest + 1, 4)


def _fingerprint(user_id: int, problem_id: int, session_id: int, category: str, concept: str) -> str:
    raw = f"{user_id}|{problem_id}|{session_id}|{category}|{concept.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def should_record_mistake(verdict: str, source: str, diag: Diagnosis | None) -> tuple[bool, str]:
    """Only journal a mistake when there is real evidence: a failure observed on
    the page AND a diagnosis the model/rules were at least medium-confident
    about. Speculation is never saved."""
    if verdict not in FAILED_VERDICTS:
        return False, "No failed submission was observed, so nothing was recorded."
    if source != "page":
        return False, "The failure was not observed on the page, so nothing was recorded."
    if diag is None:
        return False, "There was not enough evidence for a specific diagnosis, so nothing was recorded."
    if diag.confidence == "low":
        return False, "The diagnosis was too uncertain to record."
    return True, ""


def record_mistake(db: DBSession, *, user_id: int, problem: Problem, session_id: int, diag: Diagnosis,
                   verdict: str, evidence_text: str, hint_level: int, new_attempt: bool) -> MistakeObservation:
    """Insert or update. The same issue on the same problem/session updates one
    row; the same category on a DIFFERENT problem is a separate row, which is
    what lets recurring patterns be detected."""
    fp = _fingerprint(user_id, problem.id, session_id, diag.error_category, diag.concept)
    now = datetime.utcnow()
    evidence = f"verdict={verdict}; {evidence_text}"[:500]
    # Direct evidence (compiler/runtime message) + high confidence = confirmed;
    # everything else stays flagged as a hypothesis.
    is_hypothesis = not (verdict in ("compile_error", "runtime_error") and diag.confidence == "high")

    row = (db.query(MistakeObservation)
           .filter(MistakeObservation.user_id == user_id, MistakeObservation.fingerprint == fp).first())
    if row is None:
        row = MistakeObservation(
            user_id=user_id, problem_id=problem.id, session_id=session_id, fingerprint=fp,
            category=diag.error_category, concept=diag.concept,
            what_went_wrong=diag.what_went_wrong, why_happened=diag.hypothesis,
            revision_hint=diag.revision_hint, is_hypothesis=is_hypothesis,
            confidence=diag.confidence, evidence=evidence, hint_level_seen=hint_level,
            first_seen=now, last_seen=now)
        db.add(row)
    else:
        row.last_seen = now
        if new_attempt:  # a duplicate request for the same attempt must not inflate the count
            row.occurrences += 1
        row.hint_level_seen = max(row.hint_level_seen, hint_level)
        order = {"medium": 1, "high": 2}
        if order[diag.confidence] >= order[row.confidence]:  # keep the better-supported text
            row.what_went_wrong, row.why_happened = diag.what_went_wrong, diag.hypothesis
            row.revision_hint, row.confidence = diag.revision_hint, diag.confidence
            row.evidence, row.is_hypothesis = evidence, is_hypothesis
        if row.status != "unresolved":  # it happened again after being fixed
            row.status, row.resolved_at = "unresolved", None
    db.commit()
    db.refresh(row)
    return row


def resolve_session_mistakes(db: DBSession, *, user_id: int, session_id: int, highest_hint_level: int) -> int:
    """Called only on a VERIFIED Accepted. Rule: at most a conceptual probe
    (level 1) before the fix = fixed independently; anything more = with guidance."""
    status = "fixed_independently" if highest_hint_level <= 1 else "fixed_with_guidance"
    rows = (db.query(MistakeObservation)
            .filter(MistakeObservation.user_id == user_id, MistakeObservation.session_id == session_id,
                    MistakeObservation.status == "unresolved").all())
    for r in rows:
        r.status, r.resolved_at = status, datetime.utcnow()
    db.commit()
    return len(rows)


def learner_patterns(db: DBSession, user_id: int) -> list[dict]:
    """
    Per error category, computed from observations only. Evidence levels:
      single_observation   one problem (repeats on the same problem don't count as recurring)
      suspected_recurring  two distinct problems
      supported_pattern    three or more distinct problems
    Counts are evidence of *patterns*, not a score of ability.
    """
    rows = db.query(MistakeObservation).filter(MistakeObservation.user_id == user_id).all()
    by_cat: dict[str, list[MistakeObservation]] = defaultdict(list)
    for r in rows:
        by_cat[r.category].append(r)

    now = datetime.utcnow()
    out = []
    for cat, items in by_cat.items():
        problems = {r.problem_id for r in items}
        n = len(problems)
        level = "supported_pattern" if n >= 3 else "suspected_recurring" if n == 2 else "single_observation"
        resolved = sorted((r for r in items if r.status != "unresolved"), key=lambda r: r.resolved_at or r.last_seen)
        unresolved = [r for r in items if r.status == "unresolved"]
        last_seen = max(r.last_seen for r in items)
        if resolved and resolved[-1].status == "fixed_independently" and len(resolved) > 1 \
                and any(r.status == "fixed_with_guidance" for r in resolved[:-1]):
            trend = "improving"
        elif unresolved and max(unresolved, key=lambda r: r.last_seen).last_seen >= last_seen:
            trend = "needs_support"
        else:
            trend = "stable"
        confidence = min(0.9, 0.3 * n) * (0.7 if trend == "improving" else 1.0)
        out.append({
            "category": cat, "evidence_level": level, "distinct_problems": n,
            "occurrences": sum(r.occurrences for r in items),
            "unresolved": len(unresolved),
            "fixed_independently": sum(r.status == "fixed_independently" for r in items),
            "fixed_with_guidance": sum(r.status == "fixed_with_guidance" for r in items),
            "trend": trend, "confidence": round(confidence, 2),
            "last_seen": last_seen, "recent": (now - last_seen) <= timedelta(days=60),
            "concepts": sorted({r.concept for r in items})[:5],
            "problem_ids": sorted(problems),
        })
    out.sort(key=lambda p: (p["distinct_problems"], p["last_seen"]), reverse=True)
    return out


_VERDICT_PRIOR = {"time_limit_exceeded": "complexity", "memory_limit_exceeded": "complexity",
                  "runtime_error": "boundary_indexing", "compile_error": "implementation_bug",
                  "wrong_answer": "edge_case"}


def patterns_for_prompt(patterns: list[dict], verdict: str, limit: int = 3) -> list[str]:
    """Only the few patterns relevant to this verdict -- never the full history."""
    usable = [p for p in patterns if p["recent"] and (p["distinct_problems"] >= 2 or p["unresolved"])]
    prior = _VERDICT_PRIOR.get(verdict)
    usable.sort(key=lambda p: (p["category"] == prior, p["distinct_problems"], p["last_seen"]), reverse=True)
    wording = {"supported_pattern": "recurring pattern", "suspected_recurring": "suspected recurring weakness",
               "single_observation": "single earlier observation"}
    return [f"- {p['category']}: {wording[p['evidence_level']]} across {p['distinct_problems']} problem(s), "
            f"trend {p['trend']}" for p in usable[:limit]]


def learner_summary(db: DBSession, user_id: int) -> dict:
    from models import Session as SessionModel
    rows = db.query(MistakeObservation).filter(MistakeObservation.user_id == user_id).all()
    sessions = db.query(SessionModel).filter(SessionModel.user_id == user_id).all()
    by_category: dict[str, int] = defaultdict(int)
    by_status: dict[str, int] = defaultdict(int)
    weekly: dict[str, dict[str, int]] = defaultdict(lambda: {"observed": 0, "fixed_independently": 0, "fixed_with_guidance": 0})
    for r in rows:
        by_category[r.category] += 1
        by_status[r.status] += 1
        wk = (r.first_seen - timedelta(days=r.first_seen.weekday())).date().isoformat()
        weekly[wk]["observed"] += 1
        if r.status != "unresolved" and r.resolved_at:
            rk = (r.resolved_at - timedelta(days=r.resolved_at.weekday())).date().isoformat()
            weekly[rk][r.status] += 1
    return {
        "total_observations": len(rows),
        "by_category": dict(by_category),
        "by_status": dict(by_status),
        # context so counts aren't read as ability: opportunities and successes
        "problems_attempted": len({s.problem_id for s in sessions}),
        "problems_solved": len({s.problem_id for s in sessions if s.solved}),
        "weekly": [{"week": k, **v} for k, v in sorted(weekly.items())][-8:],
    }
