import { useState } from 'react'

export default function TutorChat({ hint, onRequestHint, onSubmitReasoning, canRequestHint }) {
  const [reasoning, setReasoning] = useState('')

  return (
    <div style={{ border: '1px solid #ccc', padding: '12px', marginTop: '12px' }}>
      <h3>Socrates</h3>
      {hint ? (
        <p>{hint.question}</p>
      ) : (
        <p style={{ color: '#888' }}>Submit an attempt, then ask for a hint if you're stuck.</p>
      )}

      {hint && (
        <div>
          <textarea
            placeholder="What do you think, in your own words?"
            value={reasoning}
            onChange={(e) => setReasoning(e.target.value)}
            style={{ width: '100%', height: '60px' }}
          />
          <button onClick={() => { onSubmitReasoning(reasoning); setReasoning('') }}>
            Respond
          </button>
        </div>
      )}

      <button onClick={onRequestHint} disabled={!canRequestHint} style={{ marginTop: '8px' }}>
        Ask for a hint
      </button>
    </div>
  )
}
