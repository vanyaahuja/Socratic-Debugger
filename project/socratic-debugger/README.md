# Socratic Debugger

## What's real vs. stubbed

**Real and tested:**
- `PythonRunner` / `CppRunner` — subprocess-isolated execution, tested against
  success, syntax errors, runtime errors, timeouts, compile errors, and
  segfault-style signal death. See `backend/tests/test_runners.py` (6/6 passing).
- Full DB schema (`backend/models/__init__.py`) with foreign keys enforced
  (verified: inserting a session for a nonexistent user correctly raises
  `IntegrityError`).
- End-to-end API flow verified live: create user → start session → submit
  attempt → execute code → grade against visible+hidden tests → persist →
  return results with hidden-test details stripped.

**Stubbed, needs wiring:**
- `services/tutor_service.py::_call_llm` — raises `NotImplementedError` by
  design. Plug in your LLM provider's client here (Anthropic/OpenAI/etc).
  Falls back to `FALLBACK_HINTS` so the rest of the app works without it.
- `analysis/bug_classifier.py` — coarse heuristic classification. Expand
  as you add more bug categories to the problem set.
- Frontend `CodeEditor` — plain `<textarea>`. `@monaco-editor/react` is
  already a dependency; swap the internals when ready.
- Only 5 seeded problems (ported from your original `evaluation_script.py`
  test_suite), each with 1 visible + 1 hidden test as placeholders.

## Architecture, in one pass

```
frontend (React)
   |
   v
api/            <- thin FastAPI routes, no business logic
   |
   v
services/       <- orchestration: execution, test grading, tutor prompt,
   |                hint-level progression
   v
execution/      <- language runners (Python, C++), isolated by design
analysis/       <- static/dynamic analysis feeding the tutor's bug signal
   |
   v
database/       <- repositories (raw-SQL-documented) + SQLAlchemy models
```

**Why services/ exists as a layer**: API routes never call `execution/` or
`database/repositories.py` directly except through a service function.
This is what makes "swap SQLite for Postgres" or "swap the LLM provider"
a one-file change instead of a hunt-and-replace across routes.

**Run vs. Submit**: `POST /attempts` (Run) executes code and optionally
checks visible tests, but never writes an Attempt row or touches hint
state — it's throwaway experimentation. `POST /attempts/submit` (Submit)
always persists an Attempt, runs the full test suite (visible + hidden),
and is the only thing that can trigger a hint. These are separate
functions in `api/attempts.py`, not one handler with an `is_submit` flag.

**Hidden test leakage**: `services/test_service.py::to_public_results`
and the `TestResultPublic` schema are the only allow-listed shape that
ever leaves the server for hidden tests — `passed`/`hidden`/`test_identifier`
only, never `actual_output`. Verified in the live smoke test.

**Hint escalation**: `services/progress_service.py::determine_hint_level`
holds the hint level steady (or eases back) when `tests_passed` improved
since the last attempt, and only escalates (capped at 5) when the student
is stuck or regressing. This directly implements the "don't escalate if
the student is making progress" rule.

**Leakage guard on tutor output**: `services/tutor_service.py::contains_leakage`
does a substring check against the problem's `reference_solution` before
any hint reaches the student. If the LLM's response either exceeds the
requested hint level or matches a chunk of the reference solution, it's
discarded in favor of a safe fallback hint — never surfaced raw.

## Running it

Backend:
```bash
cd backend
pip install -r requirements.txt
python -m database.seed      # seeds 5 problems from evaluation_script.py
uvicorn main:app --reload    # http://localhost:8000
```

Frontend:
```bash
cd frontend
npm install
npm run dev                  # http://localhost:5173
```

Run backend tests:
```bash
cd backend
pytest tests/ -v
```

## Migration notes (SQLite -> Postgres)

Only `database/db.py` needs to change: swap `DATABASE_URL` to a
`postgresql://` URL and drop the SQLite-specific `connect_args` and the
`PRAGMA foreign_keys=ON` listener (Postgres enforces FKs natively — SQLite
doesn't unless told to, which is why that listener exists). Everything in
`repositories.py` and above is unaffected since it only ever talks to
SQLAlchemy's ORM layer, never raw SQLite.

## Known gaps / next steps

1. Wire a real LLM client into `tutor_service._call_llm`.
2. Add a proper test-harness wrapper so student code doesn't need to
   `print()` its own output — currently each test's `stdin`/`expected_stdout`
   assumes the submitted script prints the result itself (see the NOTE in
   `database/seed.py`). A cleaner approach: wrap submitted code with a
   driver that imports the function and prints `repr(fn(*args))`.
2b. That wrapper needs to be language-aware (Python `exec`-free import,
    C++ requires the student's function to be compiled against a test
    `main()` you supply, not the student's own `main()`).
3. Containerize execution (Docker/gVisor) for real untrusted-code isolation
   — current subprocess isolation is a reasonable first line of defense,
   not a security boundary against a determined attacker.
4. Auth — `USER_ID = 1` is hardcoded in the frontend.
