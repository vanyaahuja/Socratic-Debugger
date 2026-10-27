# Socratic Debugger — LeetCode Chrome extension

A Socratic tutor in the Chrome side panel next to LeetCode. It reads your code and the latest
result **only when you press a button**, guides you with progressive hints instead of answers,
and keeps a revision journal ("My Mistakes") plus a rule-based learner profile.

For a code-grounded architecture walkthrough and interview preparation Q&A, see
[PROJECT_INTERVIEW_GUIDE.md](./PROJECT_INTERVIEW_GUIDE.md).
For focused questions and answers about the Chrome extension itself, see
[EXTENSION_QA_GUIDE.md](./EXTENSION_QA_GUIDE.md).
For a file-by-file map of the source tree and how its modules connect, see
[CODEBASE_OVERVIEW.md](./CODEBASE_OVERVIEW.md).

```
Chrome side panel (React, same bundle as the dev UI)
   │  chrome.scripting reads: title, statement, language, editor code, result panel
   ▼
FastAPI  /ext/*   (token auth, ownership checks, rate limits, validated models)
   │
   ├─ services/tutor_service.py   Gemini (existing client) + deterministic fallback + output guards
   ├─ services/progress_service.py hint ladder, mistake journal, learner patterns (rule-based)
   └─ SQLite (existing models + MistakeObservation)
```

## Setup (Windows PowerShell shown; macOS/Linux equivalents are the obvious ones)

**1. Backend**
```powershell
cd backend
.venv\Scripts\activate            # your existing virtualenv
pip install -r requirements.txt
# backend\.env must contain:  GEMINI_API_KEY=...   (optional: GEMINI_MODEL=...)
python -m database.seed           # only needed for the original practice UI
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```
Existing `socratic_debugger.db` files are upgraded in place on startup (additive columns only).

**2. Build and load the extension**
```powershell
cd frontend
npm install
npm run build                     # produces frontend\dist  (a complete MV3 extension)
```
Chrome → `chrome://extensions` → enable **Developer mode** → **Load unpacked** → choose `frontend\dist`.
Needs Chrome 114+. After code changes: `npm run build`, then click reload on the extension card.

**3. Use it**: open `https://leetcode.com/problems/<any-problem>/`, click the extension icon.

## Test the full workflow
1. Open a problem, write a solution with a bug, press **Submit** on LeetCode.
2. Side panel → **Preview what is sent** (shows exactly what was collected and what is missing), then **Analyze my code**.
3. Read the hint, answer in the box → the tutor replies using the whole conversation.
4. Fix the code, Submit again, **Analyze again…** (the hint level only goes up if you're stuck).
5. Get *Accepted* → state becomes **Solved (verified)** and the journal entry becomes *fixed independently / with guidance*.
6. Open a second problem and repeat with a similar mistake → **My Mistakes → Recurring**; later prompts include that pattern.
7. **My Mistakes**: search, filter, *Revision mode* (hint first, reveal later), mark reviewed/for revision, delete.
8. Privacy section → **Delete all my stored history**.

Automated: `cd backend && python -m pytest tests -q` (39 tests; the LLM is mocked) and, for the adapter, see "Verification status".

## Behaviour that matters
- **Verified vs reported.** "Solved" is set only when an *Accepted* **submission** is read from the page. "I think it's fixed" and a *Run* that passes the sample cases are recorded as unverified and never mark a problem solved.
- **No overclaiming.** A bare Wrong Answer cannot yield a root-cause claim: confidence is capped (medium without a failing input, low if the result wasn't observed on the page). Low-confidence diagnoses are never journaled; journaled ones are labelled *hypothesis* unless a compiler/runtime error confirms them.
- **Hint ladder:** 1 conceptual probe → 2 evidence-based → 3 targeted → 4 detailed explanation (also via *Explain the root cause*) → 5 transfer check (only after a verified Accepted). Asking again without changing code escalates; improved code holds the level; chat replies never escalate. Full corrected solutions are rejected by a server-side guard.
- **Dedup.** Same code + same result = one attempt, no new journal entry. Same mistake in the same problem/session updates one row; the same category on another problem is a new row (that's what makes patterns).
- **Patterns** (rule-based, from the same rows as the journal): 1 problem = single observation, 2 = suspected recurring, 3+ = supported pattern; trend improving/needs support/stable. Counts are presented as evidence of habits, never as a skill score. Only the 3 most relevant patterns are sent to Gemini.
- **Gemini down / bad output** (timeout 20 s, invalid JSON, over-level, pasted solution) → deterministic, verdict-aware fallback; compile/runtime/TLE/MLE errors still produce a rule-based diagnosis.
- **Untrusted input.** Code, statement, feedback and chat text are wrapped in `<untrusted_*>` tags (closing-tag injection is stripped) and the prompt instructs the model to treat them as data. Code is never executed by the API.
- **State model:** `READY → ANALYZING → HINT_AVAILABLE | REVISION_PENDING → ANALYZING … → SOLVED`. A second request while one is running gets 409.

## Privacy / security
- Sent only on button press: title/number, statement, language, editor code, result text → *your* backend → trimmed to Gemini. No cookies/credentials/other page content. The Gemini key stays in `backend/.env`.
- Stored: problem identity (not statement), verdicts, ≤1000 chars of feedback, conversation, short mistake summaries. Source code is kept only for the latest 2 attempts per session.
- Auth: random per-install token in `chrome.storage.local`; only its SHA-256 is stored. All `/ext` routes check ownership (other users' ids return 404). Rate limits: 12 analyses/min, 120 requests/min (in-memory, single process).
- Permissions: `sidePanel`, `scripting`, `storage`; hosts only `leetcode.com/problems/*` and `localhost:8000`. No remote code.
- CORS now allows only `localhost:5173` and Chrome-extension origins (was `*`). Behind a cloud IDE set `CORS_EXTRA_ORIGINS=https://your-url`.
- The original dev routes (`/problems`, `/sessions`, `/attempts/*`, `/users/*`) are unchanged and **unauthenticated**; run the backend on 127.0.0.1 only.

## Verification status (honest)
Verified: backend (39 tests incl. migration of an old DB, ownership, injection, failure modes, concurrency), a real uvicorn run over HTTP, the extension build (valid MV3 package, no inline/remote scripts), and the page adapter against **synthetic** pages.
**Not verified:** loading in a real Chrome, the side panel UI interactively, LeetCode's real page markup (the selectors in `src/leetcodeContext.js` are best-effort guesses and are the first thing to adjust if a field shows up under "Could not collect"), and live Gemini responses. LeetCode has no supported extension API; review its Terms of Service and the Chrome Web Store policies before distributing.

## Original practice UI
`npm run dev` still serves the original local practice app (runnable Python/C++ problems, `/attempts/*` routes) in a normal browser tab; the same bundle renders the extension UI when loaded as an extension.
