import { useCallback, useEffect, useRef, useState } from 'react'
import { extApi } from './api/client'
import { collectLeetCodeContext } from './leetcodeContext'
import { collectPageContext } from './pageCollection'
import TutorChat from './components/TutorChat'
import JournalPanel from './JournalPanel'
import useTheme from './useTheme'
import './extension.css'

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
  const [theme, toggleTheme] = useTheme()
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
      setInfo('Saved to your revision journal. Notes grow as you analyze code changes.')
      if (res.journal_needs_generation && res.journal_id) {
        setInfo('The result is saved. Preparing your revision notes…')
        // Separate from the tutor turn: note generation cannot consume its
        // session lease or make a successful tutoring reply fail.
        extApi.generateJournal(res.journal_id).then(() => {
          if (slugRef.current === requestedSlug) setInfo('Revision notes saved in My Mistakes.')
        }).catch((e) => {
          if (slugRef.current === requestedSlug) setInfo(`Tutor reply saved. Notes need a retry in My Mistakes: ${e.message}`)
        }).finally(() => window.dispatchEvent(new window.Event('socratic-journal-updated')))
      }
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

  return <div className="extension-app" data-theme={theme}>
    <header className="app-header">
      <div className="brand-row"><div className="brand"><span className="brand-mark" aria-hidden="true">s.</span><div><h1>Socratic Debugger</h1><div className="brand-caption">A little guidance. Your own solution.</div></div></div>
        <button className="theme-toggle" onClick={toggleTheme} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`} title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>{theme === 'dark' ? '☀' : '☾'}</button></div>
      <nav className="main-tabs" role="tablist" aria-label="Extension views">
        <button role="tab" aria-selected={view === 'tutor'} onClick={() => setView('tutor')}>Tutor</button>
        <button role="tab" aria-selected={view === 'journal'} onClick={() => setView('journal')}>My Mistakes</button>
      </nav>
    </header>
    <main className="app-content">
      {view === 'journal' ? <JournalPanel /> : <>
        {!active ? <div className="empty-state"><div className="empty-symbol">↗</div><h2>A fresh way to get unstuck</h2><p>Open a LeetCode problem, then come back here. Your code is read only when you ask.</p></div> : <>
          <section className="problem-card"><div className="eyebrow">ON YOUR DESK</div><h2>{ctx?.problem?.title || active.slug.replace(/-/g, ' ')}</h2>
            <div className="badges"><span className="badge">{STATE_LABEL[sessionState] || sessionState}</span>{ctx?.language && <span className="badge">{ctx.language}</span>}</div>
            {VERIFY_LABEL[verification] && <p className="notice">{VERIFY_LABEL[verification]}</p>}
          </section>
          <button className="primary analyze" onClick={() => requestHelp()} disabled={busy}><span>{busy ? 'Working through it…' : 'Analyze my code'}</span><span aria-hidden="true">↗</span></button>
          <div className="secondary-actions"><button onClick={() => requestHelp({ explain: true })} disabled={busy}>Explain the cause</button>
            <button onClick={() => requestHelp({ claimFixed: true })} disabled={busy} title="Self-reported until an Accepted submission is read">I think it’s fixed</button>
            <button onClick={preview} disabled={busy}>Preview what is sent</button></div>
          {error && <p className="notice error" role="alert">{error}</p>}
          {info && <p className="notice" role="status">{info}</p>}
          {ctx && <details className="context-preview"><summary>Context collected from this page</summary><ul>
            <li>Problem: {ctx.problem?.title || 'Not found'}</li>
            <li>Statement: {ctx.problem?.statement?.length || 0} characters</li>
            <li>Code: {ctx.code ? ctx.code.split('\n').length + ' lines' : 'Not found'}</li>
            <li>Result: {ctx.submission?.status || 'unknown'} · {ctx.submission?.kind || 'none'}</li>
          </ul>{ctx.submission?.message && <pre>{ctx.submission.message}</pre>}
            {ctx.missing?.length > 0 && <p>Could not collect: {ctx.missing.join(', ')}</p>}
            {ctx.notes?.map((note) => <p key={note}>{note}</p>)}
          </details>}
          <TutorChat key={active.slug} messages={messages} canRequestHint={!!active} canReply={!!sessionId} waiting={busy}
            hintLabel="Analyze again with my latest code" onRequestHint={() => requestHelp()} onSubmitReasoning={sendReply} />
        </>}
        <details className="privacy"><summary>Privacy & your saved notes</summary>
          <p>Only when you ask, the extension sends the problem, editor code, language and visible result to your backend. Trimmed context goes to the primary AI provider and, if enabled, its backup.</p>
          <p>The revision journal saves plain-language explanations, never code snippets. Tutoring history keeps at most two code versions per session: the latest and an earlier unsolved version when available. A separate AI request may generate missing notes after acceptance or when you press Generate notes. Inferred explanations are labelled for review.</p>
          <p>No cookies or LeetCode account details are collected. Keep a database backup; local history is not automatically synced across devices.</p>
          <button onClick={deleteAll}>Delete all my stored history</button>
        </details>
      </>}
    </main>
  </div>
}
