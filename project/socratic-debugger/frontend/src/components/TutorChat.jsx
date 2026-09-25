import { useState } from 'react'

/**
 * `messages` entries: { from: 'tutor'|'student', text, responseType?, reasoningStage? }
 * responseType/reasoningStage are only set on tutor messages (they come
 * straight from the TutorHint schema).
 *
 * The Respond box only appears when the last tutor message actually
 * expects a reply: response_type "question" or "acknowledgement", and
 * reasoning_stage not yet "resolved". An "instruction" or "solution" (or
 * a resolved stage) means there's nothing left to respond to -- showing
 * an empty prompt there is exactly the confusing "nothing happens" gap
 * this schema was added to fix.
 */
export default function TutorChat({ messages, onRequestHint, onSubmitReasoning, canRequestHint, waiting }) {
  const [reasoning, setReasoning] = useState('')
  const last = messages.length > 0 ? messages[messages.length - 1] : null
  const lastIsTutor = last?.from === 'tutor'
  const awaitingReply =
    lastIsTutor &&
    last.reasoningStage !== 'resolved' &&
    (last.responseType === 'question' || last.responseType === 'acknowledgement')

  function handleRespond() {
    if (!reasoning.trim()) return
    onSubmitReasoning(reasoning)
    setReasoning('')
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
            {m.from === 'tutor' && m.reasoningStage === 'resolved' && (
              <div style={{ fontSize: '12px', color: '#16a34a', marginTop: '4px' }}>Resolved</div>
            )}
          </div>
        ))}
        {waiting && <div style={{ color: '#888' }}>Socrates is thinking…</div>}
      </div>

      {awaitingReply && (
        <div>
          <textarea
            placeholder="What do you think, in your own words?"
            value={reasoning}
            onChange={(e) => setReasoning(e.target.value)}
            style={{ width: '100%', height: '60px' }}
          />
          <button onClick={handleRespond} disabled={waiting}>Respond</button>
        </div>
      )}

      <button onClick={onRequestHint} disabled={!canRequestHint || waiting} style={{ marginTop: '8px' }}>
        Ask for a hint
      </button>
    </div>
  )
}
