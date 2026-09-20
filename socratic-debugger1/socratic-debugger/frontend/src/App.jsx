import { useEffect, useState } from 'react'
import { api } from './api/client'
import CodeEditor from './components/CodeEditor'
import TestResults from './components/TestResults'
import TutorChat from './components/TutorChat'

// Hardcoded for the scaffold -- replace with real auth/user selection.
const USER_ID = 1

export default function App() {
  const [problems, setProblems] = useState([])
  const [problem, setProblem] = useState(null)
  const [sessionId, setSessionId] = useState(null)
  const [code, setCode] = useState('')
  const [runOutput, setRunOutput] = useState(null)
  const [submitResult, setSubmitResult] = useState(null)
  const [lastAttemptId, setLastAttemptId] = useState(null)
  const [hint, setHint] = useState(null)

  useEffect(() => {
    api.listProblems().then(setProblems).catch(console.error)
  }, [])

  async function selectProblem(p) {
    setProblem(p)
    setCode(p.starter_code)
    setRunOutput(null)
    setSubmitResult(null)
    setHint(null)
    const session = await api.startSession(USER_ID, p.id)
    setSessionId(session.id)
  }

  async function handleRun() {
    const result = await api.runCode(sessionId, problem.language, code)
    setRunOutput(result)
  }

  async function handleSubmit() {
    const result = await api.submitAttempt(sessionId, problem.language, code)
    setSubmitResult(result)
    setLastAttemptId(result.attempt_id)
    setHint(null)
  }

  async function handleRequestHint() {
    const h = await api.requestHint(lastAttemptId)
    setHint(h)
  }

  async function handleSubmitReasoning(text) {
    await api.submitReasoning(lastAttemptId, text)
  }

  return (
    <div style={{ display: 'flex', gap: '16px', padding: '16px', fontFamily: 'sans-serif' }}>
      <aside style={{ width: '220px' }}>
        <h2>Problems</h2>
        <ul style={{ listStyle: 'none', padding: 0 }}>
          {problems.map((p) => (
            <li key={p.id}>
              <button onClick={() => selectProblem(p)} style={{ width: '100%', textAlign: 'left' }}>
                {p.title} <small>({p.difficulty})</small>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <main style={{ flex: 1 }}>
        {problem ? (
          <>
            <h2>{problem.title}</h2>
            <p>{problem.description}</p>
            <CodeEditor code={code} onChange={setCode} language={problem.language} />
            <div style={{ marginTop: '8px' }}>
              <button onClick={handleRun}>Run</button>{' '}
              <button onClick={handleSubmit}>Submit</button>
            </div>

            {runOutput && (
              <pre style={{ background: '#f5f5f5', padding: '8px', marginTop: '8px' }}>
                {runOutput.stdout || runOutput.error_message}
              </pre>
            )}

            <TestResults result={submitResult} />

            <TutorChat
              hint={hint}
              canRequestHint={!!lastAttemptId}
              onRequestHint={handleRequestHint}
              onSubmitReasoning={handleSubmitReasoning}
            />
          </>
        ) : (
          <p>Select a problem to begin.</p>
        )}
      </main>
    </div>
  )
}
