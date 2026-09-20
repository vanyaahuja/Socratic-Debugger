const BASE_URL = 'http://localhost:8000'

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
