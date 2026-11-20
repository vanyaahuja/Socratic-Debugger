# Revision journal and palette-based themes

## User workflow

1. Analyze a problem before changing the code. A journal draft is committed to
   SQLite before generation, regardless of confidence or provider availability.
2. Fix the code, submit on LeetCode, and analyze the changed version/result.
3. The existing tutor request includes the earlier available version and current
   code. It asks for short, plain-language pointers about the clue, how the
   observed change helps, and a reminder for next time. No extra model call is
   added. The server saves a fix only when versions differ and the current
   outcome is Accepted or explicitly user-reported solved.
4. Open My Mistakes to search, edit, mark reviewed, export, or hide the fix and
   try recalling it. Earlier records/patterns remain available in a secondary
   view. Previous tutoring sessions are backfilled as drafts, not invented fixes.

The journal stores problem identity, prose pointers, verification/review flags
and an update time. It never stores a source snippet or diff. The existing
Attempt table still keeps only the latest two code versions per session for
tutoring; this PR does not add another source-code store. The fix comparison is
against the available preceding version, not necessarily the original version
from the start of a long session. If the baseline has been pruned or never
captured, the fix remains pending and can be edited manually.

AI notes are always labelled as inferred. Acceptance verifies the submission,
not the explanation or which of several changes caused success. Unknown prior
verdicts and truncated code comparisons force the uncertain flag. The model is
instructed to leave unsupported details empty. Code fences, code-like assignments
and copied source lines are screened before storing pointers; users can correct
the prose. Manually edited notes are not overwritten by later generations.
The "How I checked it" text is derived from observed vs user-reported outcomes,
not invented traces or tests. A later user report cannot downgrade a verified
accepted outcome.

## Backend changes

- `models.RevisionJournal`: new table with one entry per profile/problem.
  Existing tables and historical mistake records are preserved.
- `services/journal_service.py`: draft persistence, plain-text checks, guarded
  note updates and history backfill. Draft/outcome persistence survives LLM errors.
- `schemas.JournalPointers`: optional structured field in the tutor response.
  The existing provider schema validation and failover apply to the same request.
- `api/journal.py`: authenticated list/edit endpoints with ownership checks;
  responses expose no submitted source code. Delete-all history also deletes
  journal entries before clearing sessions.
- `api/leetcode.py` and `tutor_service.py`: attach version comparison context
  and persist validated prose. Legacy high-confidence learner-pattern rules
  remain independent, so uncertain notes do not become asserted skill patterns.

## UI and themes

The palette is #131b2b (navy), #2f4a63 (slate), #5b91a3 (teal), and #cfeae0
(mint), with derived light/dark surfaces. No remote font or image is required.
`extension.css` contains scoped CSS variables. The header toggle uses system
preference initially and saves the selected light/dark mode in
`chrome.storage.local`. A slow preference load cannot undo a user's toggle.

The tutor has a compact problem card, one primary action, quieter secondary
actions, collapsible evidence, and a persistent composer with Enter/Shift+Enter.
The journal uses readable cards and distinguishes verified acceptance,
self-reported success, and pending/inferred explanations. Search, revision
reveal, edit, review and JSON export operate on code-free entries. Legacy
mistake/profile features are retained and use the same theme variables.

## Update steps

1. Save any local work, stop FastAPI and back up your SQLite database.
2. Merge the PR and update your local checkout; preserve `.env`.
3. Activate your backend environment, install requirements as usual, and restart
   FastAPI. Startup `create_all` creates the new journal table without deleting
   existing data. No provider key/model changes are required.
4. In `frontend`, run `npm ci`, `npm test`, and `npm run build`.
5. Reload the extension at `chrome://extensions`, refresh LeetCode and reopen it.

No generated build, dependency directory, database or credentials belong in the
PR. The local fixture preview files used during development are excluded too.

## Validation and remaining checks

Backend tests cover draft retention during outages, low-confidence retention,
code-comparison notes, missing/unchanged baselines, unverified outcomes, code
screening, protected manual edits, profile isolation, backfill and deletion.
Frontend tests cover prose/verification display, draft/empty/error states,
recall/reveal, editing, saved theme preferences and existing chat/extraction
behavior. Provider HTTP is mocked, so no real quota is consumed.

The local browser preview could not connect (connection timeout), so appearance
has not been visually verified in a live side panel. Live model note quality and
LeetCode DOM extraction still need checking with your configured providers.
Optional journal notes that a model omits remain pending rather than fabricated.
Free-tier capacity and the previously documented public-deployment constraints
still apply. The local practice app is retained; the new theme is scoped to the
extension interface.
