// In local dev, http://localhost:8000 works. In a cloud IDE (Codespaces,
// Gitpod, etc.) the backend is served on its own forwarded/public URL, not
// literally "localhost" from the browser's perspective -- set
// VITE_API_URL (in a .env file, or in the cloud IDE's env panel) to that
// forwarded URL, e.g. https://<your-space>-8000.app.github.dev
const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const detail = await res.text()
    throw new Error(`${res.status}: ${detail}`)
  }
  return res.json()
}

export const api = {
  listProblems: () => request('/problems'),
  getProblem: (id) => request(`/problems/${id}`),
  startSession: (userId, problemId) =>
    request('/sessions', {
      method: 'POST',
      body: JSON.stringify({ user_id: userId, problem_id: problemId }),
    }),
  runCode: (sessionId, language, code) =>
    request('/attempts', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, language, code }),
    }),
  submitAttempt: (sessionId, language, code) =>
    request('/attempts/submit', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, language, code }),
    }),
  requestHint: (attemptId) =>
    request(`/attempts/${attemptId}/hint`, { method: 'POST' }),
  submitReasoning: (attemptId, studentResponse) =>
    request(`/attempts/${attemptId}/reasoning`, {
      method: 'POST',
      body: JSON.stringify({ attempt_id: attemptId, student_response: studentResponse }),
    }),
  getProgress: (userId) => request(`/users/${userId}/progress`),
}


// ---------------------------------------------------------------------------
// Chrome-extension API (/ext/*). The profile token is a random string created
// on first use and kept in chrome.storage.local; the backend stores only its
// hash. The base URL defaults to the local backend and can be changed by
// setting `apiBase` in chrome.storage.local (it must also be allowed in the
// manifest's host_permissions).
// ---------------------------------------------------------------------------
async function extConfig() {
  const stored = await chrome.storage.local.get(['profileToken', 'apiBase'])
  let token = stored.profileToken
  if (!token) {
    token = crypto.randomUUID().replace(/-/g, '') + crypto.randomUUID().replace(/-/g, '')
    await chrome.storage.local.set({ profileToken: token })
  }
  return { base: stored.apiBase || 'http://localhost:8000', token }
}

async function extRequest(path, { method = 'GET', body } = {}) {
  const { base, token } = await extConfig()
  let res
  try {
    res = await fetch(`${base}/ext${path}`, {
      method,
      headers: { 'Content-Type': 'application/json', 'X-Profile-Token': token },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new Error(`Can't reach the Socratic Debugger backend at ${base}. Is it running?`)
  }
  if (!res.ok) {
    let detail = `${res.status}`
    try {
      const j = await res.json()
      detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch { /* keep status */ }
    const err = new Error(detail)
    err.status = res.status
    throw err
  }
  return res.json()
}

const qs = (params) => {
  const u = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => v && u.set(k, v))
  const s = u.toString()
  return s ? `?${s}` : ''
}

export const extApi = {
  analyze: (payload) => extRequest('/analyze', { method: 'POST', body: payload }),
  reply: (sessionId, message, statement) =>
    extRequest(`/session/${sessionId}/reply`, { method: 'POST', body: { message, statement } }),
  sessionBySlug: (slug) => extRequest(`/session/by-slug/${slug}`),
  mistakes: (params = {}) => extRequest(`/mistakes${qs(params)}`),
  patchMistake: (id, patch) => extRequest(`/mistakes/${id}`, { method: 'PATCH', body: patch }),
  deleteMistake: (id) => extRequest(`/mistakes/${id}`, { method: 'DELETE' }),
  explain: (id, mode) => extRequest(`/mistakes/${id}/explain`, { method: 'POST', body: { mode } }),
  patterns: () => extRequest('/patterns'),
  summary: () => extRequest('/summary'),
  deleteHistory: () => extRequest('/history', { method: 'DELETE' }),
}
