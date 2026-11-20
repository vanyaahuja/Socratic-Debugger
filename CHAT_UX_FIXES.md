# Chat continuation and submission feedback

## What changed

- The reply box stays available whenever a tutoring session has messages,
  including after `resolved`, `instruction`, and Accepted turns. Model metadata
  describes its answer; it no longer decides whether the learner may speak.
- Enter sends. Shift+Enter inserts a newline. Input-method composition,
  held/repeated Enter keys, empty messages, and an in-flight send cannot trigger
  duplicate submissions. Failed drafts and newly typed drafts are preserved.
- The former model-generated "Resolved" badge now says "Reasoning complete ·
  follow-up questions welcome". The separate server-verified submission status
  remains authoritative for whether LeetCode accepted the solution.
- The result reader tries known result markers, accessibility-labelled result
  panels, then compact exact verdict headings next to testcase counts or
  input/output/expected fields. It ignores hidden result containers and problem
  description/editor/navigation elements. It does not read cookies, intercept
  network traffic, or call LeetCode's internal API.
- Wrong Answer feedback retains the passed/total count and bounded input,
  actual output and expected output blocks. The Preview shows the collected
  feedback text. A long input cannot crowd out the Output/Expected blocks.
- Expanding a case and analyzing the same code again updates its evidence
  without inventing a new attempt. Later chat replies retain that evidence,
  including a count of zero passed tests.
- Run vs Submit is persisted with the attempt. Ambiguous or sample success
  cannot become a verified submission merely because the learner sends a reply.

## Apply and run

After merging the pull request, update your local checkout. Preserve `.env` and
back up the database. Stop and restart FastAPI as usual; startup adds the
nullable `attempts.verdict_kind` column without deleting history. Old attempts
without this field are handled conservatively unless their session was already
verified solved.

From `frontend`:

```powershell
npm ci
npm test
npm run build
```

Reload the extension in `chrome://extensions`, refresh LeetCode, and reopen the
panel. Rebuilding frontend alone does not install the backend migration.

The development React plugin is updated to a version supporting the existing
Vite 8 dependency; the old plugin's peer requirements caused clean installation
to fail. JSDOM is development-only and lets the tests exercise real React
components and synthetic result pages without downloading a browser or calling
an AI provider. No key or model configuration changes are required.

## Verification and limits

- React component tests cover persistent reply controls, Enter/Shift+Enter,
  composition, duplicate prevention, waiting state and failed/new drafts.
- Serialized page-reader tests cover Wrong Answer, testcase counts, expected
  and actual output, hidden stale panels, sample vs submission success,
  long input and compiler feedback. All helper functions remain inside the
  injected function, so Chrome's serialization does not lose imports.
- Backend regression tests cover continued replies, updated evidence, zero
  passed tests, and unverified acceptance remaining unverified during chat.

These are controlled DOM fixtures, not proof that every current LeetCode layout
is supported. Browser inspection ended because the computer-use tool could not
verify the current Chrome URL. No code was submitted or changed in LeetCode.
Only visible result content is available; hidden failing cases must be expanded
on the page, then Analyze pressed again. If extraction still misses your layout,
use Preview to report the missing fields and provide the relevant result view.
The reader never treats ambiguous Accepted as verified just to make collection
look successful.
