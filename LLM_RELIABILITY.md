# Configurable LLM reliability changes

Base: `vanyaahuja/Socratic-Debugger`, commit
`1f3ba170cbb1c83cb56f4fd76712e8fd5e7e1100` on `main`.

This change keeps React, FastAPI and SQLite. It does not deploy the application,
change hosting, introduce an account system, or require Ollama/Cloudflare.
No actual API key or production model ID is included.

## What happens during one tutor turn

1. FastAPI builds one prompt from the code, feedback, relevant learner patterns,
   conversation history and latest student answer.
2. `services/llm_provider.py` sends it to the configured primary provider.
3. Temporary failures (408, 500, 502, 503, 504, network errors and timeouts) can
   be retried. `LLM_MAX_ATTEMPTS=2` means the original request plus one retry.
   Backoff includes jitter. Long or date-valued Retry-After headers cause a
   switch rather than retrying the same provider too early.
4. Quota/authentication/configuration failures are not immediately retried.
   If enabled, the backup receives the same prompt. Invalid JSON/schema or an
   answer rejected by the extension's teaching rules also triggers backup.
5. The primary gets at most half of the total deadline when backup is enabled.
   A total asynchronous deadline bounds network waits and backoff together.
6. Only a validated reply is added to the conversation. Provider switching
   does not create an extra tutor turn or duplicate the student's latest answer.

The default budget is 30 seconds total, eight seconds per network attempt,
and at most two attempts per provider. Environment settings can lower these;
the total cannot exceed 30 seconds, below the existing 45-second session lease.

If all providers fail, only the first analysis may show a visibly labelled
generic debugging prompt. It is not counted as successful AI guidance and does
not advance hint progress. Repeated analysis and conversational replies return
a safe HTTP 503 instead of appending the same canned message. The panel keeps
the existing transcript and failed draft so the learner can retry.

## Configuration

Copy `backend/.env.example` to `backend/.env` and fill it locally. Do not commit
`.env`, put keys in React/Vite variables, or paste secrets into GitHub issues.

| Setting | Meaning |
| --- | --- |
| `LLM_PRIMARY_PROVIDER` | `gemini` or `openai_compatible` |
| `LLM_PRIMARY_API_KEY` | Primary service key |
| `LLM_PRIMARY_MODEL` | Exact model ID from your account; required, no default |
| `LLM_PRIMARY_BASE_URL` | API base URL; Gemini's standard endpoint is the only default |
| `LLM_BACKUP_PROVIDER` | Empty disables backup; otherwise one of the two protocols |
| `LLM_BACKUP_API_KEY` | Backup service key |
| `LLM_BACKUP_MODEL` | Exact backup model ID; required when backup is enabled |
| `LLM_BACKUP_BASE_URL` | API base URL, without `/chat/completions` |
| `LLM_TOTAL_TIMEOUT_SECONDS` | Whole generation deadline, 1–30 seconds |
| `LLM_ATTEMPT_TIMEOUT_SECONDS` | Individual network attempt cap, 0.1–15 seconds |
| `LLM_MAX_ATTEMPTS` | 1–3 attempts per provider, including the original |
| `LLM_MAX_OUTPUT_TOKENS` | 128–4096 generated tokens; default 1024 |

For Gemini primary + Groq backup, choose `gemini` for the primary and
`openai_compatible` for the backup. Groq's base URL is
`https://api.groq.com/openai/v1`. Enter the two keys and model IDs yourself.
There is no default backup model and no guarantee that an arbitrary model
supports JSON mode. Select one that supports chat completions and JSON output.
Not every OpenAI-compatible service has identical parameter support.

Existing `GEMINI_API_KEY` and `GEMINI_MODEL` variables remain supported for
the primary Gemini provider. Unlike the old implementation, `GEMINI_MODEL`
must be explicitly set if `LLM_PRIMARY_MODEL` is empty. Missing configuration
does not crash module import, but generation cannot succeed until configured.
Restart FastAPI after editing environment settings.

Backup is opt-in. Keep it empty until you have selected and tested a model
and disclosed both providers in your deployment's privacy policy. Enabling
backup permits sending the same code/problem/chat context to that service.
An alternative key in the same quota pool is not independent capacity.

## Files to review

| File | Change and purpose |
| --- | --- |
| `backend/services/llm_provider.py` | New small HTTP adapter/router, retry policy, deadlines and output validation |
| `backend/services/tutor_service.py` | Delegates to router; teaching-rule validation before accepting backup output; safe ongoing failures |
| `backend/.env.example` | Empty key/model placeholders and documented settings |
| `backend/requirements.txt` | Removes the unnecessary Gemini SDK; uses the existing HTTPX dependency |
| `backend/api/leetcode.py` | Persists message controls; failed student replies are not committed; fallback does not advance hint progress |
| `backend/models/__init__.py` | Tutor message type/stage and fallback annotations |
| `backend/database/db.py` | Additive SQLite migration for the message columns |
| `backend/schemas/__init__.py` | Exposes those fields to the panel |
| `frontend/src/ExtensionApp.jsx` | Restores reply controls, labels fallback, keeps failed drafts, ignores stale responses after problem navigation |
| `frontend/src/components/TutorChat.jsx` | Clears a draft only after successful submission |
| `frontend/src/pageCollection.js` | Explicit empty-result/error/timeout handling for Chrome page reading |
| `frontend/src/pageCollection.test.js` | Tests page-reading success, missing output, permissions and timeout |
| `backend/tests/test_llm_provider.py` | Mocked HTTP tests of retries, backup, deadlines, configuration, safety and concurrent contexts |
| `backend/tests/test_extension_api.py` | Regression tests of continuation, restoration, migration and failure behavior |
| `README.md` | Updated setup and failure behavior |

## Compare and merge using the patch

Start from your existing repository, with your own changes saved or committed.
Make a separate branch:

```powershell
git switch -c fix/llm-reliability
git apply --stat C:/path/to/socratic-debugger-llm-reliability.patch
git apply --check C:/path/to/socratic-debugger-llm-reliability.patch
git apply C:/path/to/socratic-debugger-llm-reliability.patch
git diff --stat
git diff
git status --short
```

The patch is cumulative: it includes the earlier conversation/Preview fixes.
Apply it to the stated base once. If you already copied earlier fixes, some
hunks will already be present; compare the supplied `changed-files/` copies
instead. Do not force a failed apply or overwrite your own unrelated changes.
`git diff` does not show newly created untracked files until staged; inspect
those files directly as well. The bundle includes a unified diff for review.

Copying only `dist` is not sufficient: backend and source changes are required.
The merge patch intentionally excludes built assets, node_modules, caches,
databases and secrets. Preserve your `.env` and database; back up SQLite before
first startup. The startup migration adds columns without deleting existing
history. Old messages have no recorded type, so restoration conservatively
allows replying instead of losing the composer.

## Install, test and run

From `backend` using your activated Python environment (Python 3.12 tested):

```powershell
pip install -r requirements.txt
python -m pytest tests/test_llm_provider.py tests/test_extension_api.py -q
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

From `frontend`:

```powershell
npm ci
node --test src/pageCollection.test.js
npm run build
```

Reload the unpacked extension at `chrome://extensions`, refresh LeetCode and
reopen the side panel. Chrome executes the newly generated `frontend/dist`.

Once reviewed:

```powershell
git add README.md LLM_RELIABILITY.md backend/.env.example backend/requirements.txt backend/services/llm_provider.py backend/services/tutor_service.py backend/api/leetcode.py backend/models/__init__.py backend/database/db.py backend/schemas/__init__.py backend/tests/test_llm_provider.py backend/tests/test_extension_api.py frontend/src/ExtensionApp.jsx frontend/src/components/TutorChat.jsx frontend/src/pageCollection.js frontend/src/pageCollection.test.js
git diff --cached
git commit -m "Add configurable LLM failover and preserve tutor conversations"
git push -u origin fix/llm-reliability
```

Then open a pull request on GitHub to compare and merge. Do not include `.env`,
your database, caches, or generated dependency/build directories in this commit.

## Verification and remaining limits

All provider tests use dummy credentials and mocked HTTP; they do not consume
API quota. They verify both wire formats, 503 recovery, primary-to-backup
continuation, quota/auth errors, malformed/truncated/over-level output, timeout
reservation, complete outage, secrets-safe router logs, migration and ten
simultaneous independent contexts. That concurrency test is not a provider
capacity benchmark.

Live Gemini/Groq output quality and latency still require your own configured
accounts. Run several complete debugging conversations before publishing.
Retries cannot create free quota or guarantee availability; each attempted
generation may consume provider quota even when its response is lost.
The browser does not automatically retry mutating API requests. A lost HTTP
response after the server committed a reply can still require session restore
before manual retry; this patch does not add persistent idempotency keys.

The original local practice UI still has its original template-fallback policy;
the stricter ongoing-conversation failure behavior here targets `/ext/*`.
The LeetCode page selectors have not been verified on your current live page;
Preview now explains collection failure rather than silently doing nothing.

This patch is not a public deployment. Before hosting, exclude the original
unauthenticated execution routes, configure durable storage, restrict allowed
origins, protect against abuse and publish accurate provider disclosures.
Your existing per-profile rate limit is process-local and can be bypassed by
creating profiles. CORS alone is not authentication. The backend still has to
be hosted at an HTTPS URL and that host must be allowed in the manifest.

## Interview explanation

“React sends context to FastAPI. A provider adapter converts the same prompt
into either Gemini's request format or chat-completions format. Transient
errors get bounded retries; otherwise an optional backup is tried within the
same deadline. Pydantic and tutor rules validate output before we persist a
new turn. If generation fails, the student's draft and previous state survive.
Configuration selects the provider and model; credentials never enter the
extension bundle.”

References: [Gemini generateContent](https://ai.google.dev/api/generate-content),
[Groq compatibility](https://console.groq.com/docs/openai),
[HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/).
