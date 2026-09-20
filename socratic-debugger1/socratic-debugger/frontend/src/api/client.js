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
