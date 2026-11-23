import { useRef, useState } from 'react'

export default function TutorChat({ messages, onRequestHint, onSubmitReasoning, canRequestHint, waiting, canReply = true, hintLabel = 'Ask for a hint' }) {
  const [reasoning, setReasoning] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const sending = useRef(false)
  const input = useRef(null)
  const showComposer = canReply && messages.length > 0
  async function handleRespond() {
    if (!reasoning.trim() || waiting || sending.current || !canReply) return
    sending.current = true; setSubmitting(true)
    const submitted = reasoning
    try {
      const sent = await onSubmitReasoning(submitted)
      if (sent !== false) setReasoning((current) => current === submitted ? '' : current)
    } catch { /* Keep the draft; the parent displays the request error. */ }
    finally { sending.current = false; setSubmitting(false) }
  }
  function handleKeyDown(event) {
    if (event.key !== 'Enter' || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey
        || event.nativeEvent?.isComposing || event.nativeEvent?.keyCode === 229) return
    event.preventDefault()
    if (!event.repeat) handleRespond()
  }
  return <section className="tutor-card" aria-label="Tutor conversation">
    <div className="chat-heading"><span className="status-dot" /><h3>Socrates</h3><small>One hint at a time</small></div>
    {messages.length === 0 && <div className="empty-state"><h3>Find your next step</h3><p>Analyze your code to begin. We’ll work through the reasoning together.</p></div>}
    <div className="chat-log" role="log" aria-live="polite" aria-relevant="additions">
      {messages.map((m, i) => <article key={i} className={`message ${m.from === 'student' ? 'student' : 'tutor'}`}>
        <div className="message-label">{m.from === 'student' ? 'You' : 'Socrates'}</div><div className="message-text">{m.text}</div>
        {m.note && <details><summary>Evidence and confidence</summary><p>{m.note}</p></details>}
      </article>)}
      {waiting && <div className="thinking" role="status">Preparing your next hint…</div>}
    </div>
    {showComposer && <div className="composer">
      <textarea ref={input} autoFocus aria-label="Your message to the tutor" placeholder="Share your reasoning or ask a follow-up…"
        value={reasoning} onChange={(e) => setReasoning(e.target.value)} onKeyDown={handleKeyDown} />
      <div className="composer-footer"><span>Enter to send · Shift+Enter for a new line</span>
        <button className="primary" onClick={handleRespond} disabled={waiting || submitting || !reasoning.trim()}>Respond ↑</button></div>
    </div>}
    {messages.length > 0 && <button className="analyze-again" onClick={onRequestHint} disabled={!canRequestHint || waiting}>{hintLabel}</button>}
  </section>
}
