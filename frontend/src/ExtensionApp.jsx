import { useCallback, useEffect, useRef, useState } from 'react'
import { extApi } from './api/client'
import { collectLeetCodeContext } from './leetcodeContext'
import { collectPageContext } from './pageCollection'
import TutorChat from './components/TutorChat'
import MistakesPanel from './MistakesPanel'

const STATE_LABEL = {
  READY: 'Ready',
  ANALYZING: 'Analyzing…',
  HINT_AVAILABLE: 'Hint available',
  REVISION_PENDING: 'Revise your code, then ask again',
  SOLVED: 'Solved (verified)',
}

const VERIFY_LABEL = {
  verified_accepted: 'Accepted on LeetCode (verified)',
  unverified_user_report: 'You reported success — not verified yet. Submit on LeetCode and ask again.',
  pending: 'Submission still running',
  not_accepted: null,
}

async function readActiveLeetCodeTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true })
  const m = tab?.url?.match(/^https:\/\/leetcode\.com\/problems\/([a-z0-9-]+)/)
  return m ? { tabId: tab.id, slug: m[1] } : null
}

async function collectFromTab(tabId) {
  return collectPageContext(chrome, tabId, collectLeetCodeContext)
}

const noteFor = (d) =>
  d
    ? `Observed: ${d.observed}  ·  Hypothesis (${d.confidence} confidence): ${d.hypothesis}`
    : null

const FALLBACK_REASON = {
  rate_limited: 'The AI provider reported a quota or rate limit.',
  authentication: 'The AI provider rejected the backend credentials or access.',
  configuration: 'The backend AI configuration is incomplete or invalid.',
  invalid_output: 'The AI response could not be read in the required format.',
  provider_unavailable: 'The AI request failed; check the backend status log.',
  rejected_output: 'The AI response exceeded the allowed hint level or included solution code.',
}

const toMessage = (tutor) => ({
  from: 'tutor',
  text: tutor.message,
  responseType: tutor.response_type,
  reasoningStage: tutor.reasoning_stage,
  note: tutor.used_fallback
    ? `${FALLBACK_REASON[tutor.fallback_reason] || 'AI unavailable.'} This is a general debugging prompt, not a personalized AI reply.`
    : noteFor(tutor.diagnosis),
})

export default function ExtensionApp() {
  const [view, setView] = useState('tutor')
  const [active, setActive] = useState(null) // { tabId, slug } of the current LeetCode problem
  const [sessionId, setSessionId] = useState(null)
  const [sessionState, setSessionState] = useState('READY')
  const [messages, setMessages] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [info, setInfo] = useState(null)
  const [verification, setVerification] = useState(null)
  const [ctx, setCtx] = useState(null) // last collected context (preview / what was sent)
  const statementRef = useRef('')
  const slugRef = useRef(null)

  // Follow the active tab / SPA navigation between problems.
  const refreshActive = useCallback(async () => {
    const a = await readActiveLeetCodeTab()
    setActive(a)
  }, [])
  useEffect(() => {
    refreshActive()
    const onUpdated = (_id, change) => { if (change.url || change.status === 'complete') refreshActive() }
    chrome.tabs.onActivated.addListener(refreshActive)
    chrome.tabs.onUpdated.addListener(onUpdated)
    chrome.windows.onFocusChanged.addListener(refreshActive)
    return () => {
      chrome.tabs.onActivated.removeListener(refreshActive)
      chrome.tabs.onUpdated.removeListener(onUpdated)
      chrome.windows.onFocusChanged.removeListener(refreshActive)
    }
  }, [refreshActive])

  // New problem -> restore its recent conversation (if any) from the backend.
  useEffect(() => {
    const slug = active?.slug ?? null
    if (slug === slugRef.current) return
    slugRef.current = slug
    setSessionId(null); setMessages([]); setSessionState('READY'); setVerification(null)
    setCtx(null); setError(null); setInfo(null)
    if (!slug) return
    extApi.sessionBySlug(slug).then((s) => {
      if (!s || slugRef.current !== slug) return
      setSessionId(s.session_id)
      setSessionState(s.state)
      setMessages(s.messages.map((m) => ({ from: m.sender, text: m.text,
        responseType: m.response_type || (m.sender === 'tutor' ? 'question' : undefined),
        reasoningStage: m.reasoning_stage,
        note: m.used_fallback ? `${FALLBACK_REASON[m.fallback_reason] || 'AI unavailable.'} General debugging prompt.` : null })))
    }).catch(() => { /* backend offline: the error appears when the student asks for help */ })
  }, [active])

  const collect = async () => {
    const c = await collectFromTab(active.tabId)
    if (c.problem?.slug && c.problem.slug !== slugRef.current) {
      throw new Error('The active problem changed. Reopen the panel on the new problem and try again.')
    }
    setCtx(c)
    statementRef.current = c?.problem?.statement || ''
    return c
  }

  const preview = async () => {
    if (busy) return
    setBusy(true); setError(null); setInfo('Reading the LeetCode page…')
    try {
      const c = await collect()
      if (!c.ok) throw new Error('This tab is not a LeetCode problem page.')
      setInfo('Preview updated below. This action does not send data to the backend or AI provider.')
    } catch (e) {
      setInfo(null)
      setError(e.message || 'Could not read this page.')
    } finally {
      setBusy(false)
    }
  }

  const requestHelp = async ({ explain = false, claimFixed = false } = {}) => {
    if (!active || busy) return
    const requestedSlug = slugRef.current
    setBusy(true); setError(null); setInfo(null)
    try {
      const c = await collect()
      if (slugRef.current !== requestedSlug) return
      if (!c?.ok) throw new Error('This tab is not a LeetCode problem page.')
      if (!c.code) throw new Error('Could not read your code from the page. Click inside the editor once and try again.')
      const submission = claimFixed
        ? { status: 'accepted', source: 'user_reported', kind: 'none', message: null }
        : c.submission
      const res = await extApi.analyze({
        problem: c.problem,
        language: c.language || 'unknown',
        code: c.code,
        submission,
        session_id: sessionId,
        request_explanation: explain,
        missing_context: c.missing,
      })
      if (slugRef.current !== requestedSlug) return
      setSessionId(res.session_id)
      setSessionState(res.state)
      setVerification(res.verification)
      setMessages((prev) => [...prev, toMessage(res.tutor)])
      if (res.mistake_recorded) setInfo('Saved to My Mistakes' + (res.tutor.diagnosis?.confidence ? ` (${res.tutor.diagnosis.confidence} confidence, hypothesis)` : ''))
      else if (res.duplicate_attempt) setInfo('Your code and result have not changed since your last request.')
      else if (res.mistake_note) setInfo(res.mistake_note)
    } catch (e) {
      if (slugRef.current === requestedSlug) setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const sendReply = async (text) => {
    if (!sessionId || busy) return false
    const requestedSlug = slugRef.current
    setBusy(true); setError(null); setInfo(null)
    try {
      const res = await extApi.reply(sessionId, text, statementRef.current)
      if (slugRef.current !== requestedSlug) return false
      setSessionState(res.state)
      setMessages((prev) => [...prev, { from: 'student', text }, toMessage(res.tutor)])
      return true
    } catch (e) {
      if (slugRef.current === requestedSlug) setError(e.message)
      return false
    } finally {
      setBusy(false)
    }
  }

  const deleteAll = async () => {
    if (!window.confirm('Delete ALL stored tutoring history and mistakes for this profile? This cannot be undone.')) return
    try {
      await extApi.deleteHistory()
      setSessionId(null); setMessages([]); setSessionState('READY'); setVerification(null)
      setInfo('All stored history was deleted.')
    } catch (e) { setError(e.message) }
  }

  const tabBtn = (id, label) => (
    <button onClick={() => setView(id)} style={{ flex: 1, padding: '8px', border: 'none', cursor: 'pointer',
      borderBottom: view === id ? '3px solid #2563eb' : '3px solid transparent', background: 'none',
      fontWeight: view === id ? 700 : 400 }}>{label}</button>
  )

  return (
    <div style={{ fontFamily: 'sans-serif', fontSize: '14px', padding: '8px', minWidth: '300px' }}>
      <div style={{ display: 'flex', borderBottom: '1px solid #ddd', marginBottom: '8px' }}>
        {tabBtn('tutor', 'Tutor')}
        {tabBtn('mistakes', 'My Mistakes')}
      </div>

      {view === 'mistakes' ? <MistakesPanel /> : (
        <>
          {!active ? (
            <p style={{ color: '#666' }}>
              Open a LeetCode problem page (leetcode.com/problems/…) in the active tab to get started.
            </p>
          ) : (
            <>
              <div style={{ marginBottom: '6px' }}>
                <strong>{ctx?.problem?.title || active.slug}</strong>
                <span style={{ color: '#666' }}> · {STATE_LABEL[sessionState] || sessionState}</span>
              </div>
              {VERIFY_LABEL[verification] && (
                <div style={{ color: verification === 'verified_accepted' ? '#16a34a' : '#b45309', marginBottom: '6px' }}>
                  {VERIFY_LABEL[verification]}
                </div>
              )}

              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                <button onClick={() => requestHelp()} disabled={busy}>Analyze my code</button>
                <button onClick={() => requestHelp({ explain: true })} disabled={busy}>Explain the root cause</button>
                <button onClick={() => requestHelp({ claimFixed: true })} disabled={busy} title="Not verified until you submit on LeetCode">
                  I think it's fixed
                </button>
                <button onClick={preview} disabled={busy}>
                  Preview what is sent
                </button>
              </div>

              {error && <p style={{ color: '#b91c1c' }}>{error}</p>}
              {info && <p style={{ color: '#555' }}>{info}</p>}

              {ctx && (
                <details style={{ marginTop: '8px' }} open>
                  <summary>What was collected from this page</summary>
                  <ul style={{ margin: '4px 0', paddingLeft: '18px' }}>
                    <li>Problem: {ctx.problem?.frontend_id ? `${ctx.problem.frontend_id}. ` : ''}{ctx.problem?.title || '—'}</li>
                    <li>Statement: {ctx.problem?.statement ? `${ctx.problem.statement.length} characters` : '—'}</li>
                    <li>Language: {ctx.language || '—'}</li>
                    <li>Code: {ctx.code ? `${ctx.code.split('\n').length} lines` : '—'}</li>
                    <li>Latest result: {ctx.submission?.status !== 'unknown' ? `${ctx.submission.status} (${ctx.submission.kind})` : 'none visible'}</li>
                  </ul>
                  {ctx.submission?.message && <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: '12px' }}>{ctx.submission.message}</pre>}
                  {ctx.missing?.length > 0 && <div style={{ color: '#b45309' }}>Could not collect: {ctx.missing.join(', ')}</div>}
                  {ctx.notes?.map((n) => <div key={n} style={{ color: '#666' }}>Note: {n}</div>)}
                </details>
              )}

              <TutorChat
                key={active.slug}
                messages={messages}
                canReply={!!sessionId}
                canRequestHint={!!active}
                waiting={busy}
                hintLabel="Analyze again with my latest code"
                onRequestHint={() => requestHelp()}
                onSubmitReasoning={sendReply}
              />
            </>
          )}

          <details style={{ marginTop: '12px' }}>
            <summary>Privacy: what is sent and stored</summary>
            <p style={{ margin: '6px 0' }}>
              <strong>Sent</strong> only when you press a button: the problem title/number, the problem statement,
              your language, the code in the editor, and the latest result text shown on the page — to your own
              backend, which sends a trimmed version to its AI provider. If a backup provider is enabled,
              the same context may be sent there when the primary fails. No cookies, account details, or
              other page content are read.
            </p>
            <p style={{ margin: '6px 0' }}>
              <strong>Stored</strong> locally in SQLite: problem identity, verdicts, short feedback, the tutoring
              conversation, and short mistake summaries. Source code is kept only for your latest two attempts per
              session; the statement is not stored.
            </p>
            <button onClick={deleteAll}>Delete all my stored history</button>
          </details>
        </>
      )}
    </div>
  )
}
