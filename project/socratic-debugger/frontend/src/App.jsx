import { useEffect, useRef, useState } from 'react'
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
  const [messages, setMessages] = useState([])   // conversation thread for the current attempt
  const [waitingOnTutor, setWaitingOnTutor] = useState(false)
  // Mirrors lastAttemptId but read inside the async hint request after the
  // await -- a plain closure over lastAttemptId would be stale (captured
  // at call time, before any newer Submit could update it), so a ref is
  // used to always see the latest value at resolution time.
  const lastAttemptIdRef = useRef(null)

  useEffect(() => {
    api.listProblems().then(setProblems).catch(console.error)
  }, [])

  async function selectProblem(p) {
    setProblem(p)
    setCode(p.starter_code)
    setRunOutput(null)
    setSubmitResult(null)
    setMessages([])
    setLastAttemptId(null)
    lastAttemptIdRef.current = null
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
    lastAttemptIdRef.current = result.attempt_id
    setMessages([])
  }

  async function handleRequestHint() {
    const requestedFor = lastAttemptId
    setWaitingOnTutor(true)
    try {
      const h = await api.requestHint(requestedFor)
      // Guard against out-of-order responses: if the user submitted a new
      // attempt (or picked a new problem) while this request was in flight,
      // the ref will have moved on -- discard the stale reply instead of
      // appending it to the wrong attempt's thread.
      if (requestedFor !== lastAttemptIdRef.current) return
      setMessages((prev) => [
        ...prev,
        { from: 'tutor', text: h.message, responseType: h.response_type, reasoningStage: h.reasoning_stage },
      ])
    } finally {
      if (requestedFor === lastAttemptIdRef.current) setWaitingOnTutor(false)
    }
  }

  async function handleSubmitReasoning(text) {
    const requestedFor = lastAttemptId
    setMessages((prev) => [...prev, { from: 'student', text }])
    setWaitingOnTutor(true)
    try {
      const reply = await api.submitReasoning(requestedFor, text)
      if (requestedFor !== lastAttemptIdRef.current) return
      setMessages((prev) => [
        ...prev,
        { from: 'tutor', text: reply.message, responseType: reply.response_type, reasoningStage: reply.reasoning_stage },
      ])
    } finally {
      if (requestedFor === lastAttemptIdRef.current) setWaitingOnTutor(false)
    }
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
              messages={messages}
              canRequestHint={!!lastAttemptId}
              waiting={waitingOnTutor}
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
