import { useRef, useState } from 'react'

/**
 * `messages` entries: { from: 'tutor'|'student', text, responseType?, reasoningStage? }
 * responseType/reasoningStage are only set on tutor messages (they come
 * straight from the TutorHint schema).
 *
 * Model metadata describes the tutor's turn; it must never lock the learner
 * out of asking another question. A resolved explanation can still have a
 * reflection question, and an instruction can need clarification.
 */
export default function TutorChat({ messages, onRequestHint, onSubmitReasoning, canRequestHint, waiting, canReply = true, hintLabel = 'Ask for a hint' }) {
  const [reasoning, setReasoning] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const sending = useRef(false)
  const input = useRef(null)
  const showComposer = canReply && messages.length > 0

  async function handleRespond() {
    if (!reasoning.trim() || waiting || sending.current || !canReply) return
    sending.current = true
    setSubmitting(true)
    const submitted = reasoning
    try {
      const sent = await onSubmitReasoning(submitted)
      if (sent !== false) setReasoning((current) => current === submitted ? '' : current)
    } catch {
      // The parent displays the error. Keep the draft available for retry.
    } finally {
      sending.current = false
      setSubmitting(false)
    }
  }

  function handleKeyDown(event) {
    if (event.key !== 'Enter' || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey
        || event.nativeEvent?.isComposing || event.nativeEvent?.keyCode === 229) return
    event.preventDefault()
    if (!event.repeat) handleRespond()
  }

  return (
    <div style={{ border: '1px solid #ccc', padding: '12px', marginTop: '12px' }}>
      <h3>Socrates</h3>

      {messages.length === 0 && (
        <p style={{ color: '#888' }}>Submit an attempt, then ask for a hint if you're stuck.</p>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '8px' }}>
        {messages.map((m, i) => (
          <div
            key={i}
            style={{
              alignSelf: m.from === 'tutor' ? 'flex-start' : 'flex-end',
              background: m.from === 'tutor' ? '#f0f0f0' : '#dbeafe',
              padding: '8px 12px',
              borderRadius: '8px',
              maxWidth: '80%',
            }}
          >
            {m.text}
            {m.note && <div style={{ fontSize: '12px', color: '#555', marginTop: '6px', borderTop: '1px solid #ddd', paddingTop: '4px' }}>{m.note}</div>}
            {m.from === 'tutor' && m.reasoningStage === 'resolved' && (
              <div style={{ fontSize: '12px', color: '#555', marginTop: '4px' }}>Reasoning complete · follow-up questions welcome</div>
            )}
          </div>
        ))}
        {waiting && <div style={{ color: '#888' }}>Socrates is thinking…</div>}
      </div>

      {showComposer && (
        <div>
          <textarea
            ref={input}
            autoFocus
            aria-label="Your message to the tutor"
            placeholder="Share your reasoning or ask a follow-up…"
            value={reasoning}
            onChange={(e) => setReasoning(e.target.value)}
            onKeyDown={handleKeyDown}
            style={{ width: '100%', height: '60px' }}
          />
          <div style={{ fontSize: '12px', color: '#666' }}>Enter to send · Shift+Enter for a new line</div>
          <button onClick={handleRespond} disabled={waiting || submitting || !reasoning.trim()}>Respond</button>
        </div>
      )}

      <button onClick={onRequestHint} disabled={!canRequestHint || waiting} style={{ marginTop: '8px' }}>
        {hintLabel}
      </button>
    </div>
  )
}
