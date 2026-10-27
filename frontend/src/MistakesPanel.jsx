import { useCallback, useEffect, useState } from 'react'
import { extApi } from './api/client'

const VIEWS = [
  ['recent', 'Recent'],
  ['needs_revision', 'Needs revision'],
  ['patterns', 'Recurring'],
  ['resolved', 'Resolved'],
  ['summary', 'Summary'],
]
const CATEGORIES = ['logic_error', 'edge_case', 'boundary_indexing', 'wrong_algorithm', 'complexity',
  'implementation_bug', 'problem_interpretation', 'other']
const STATUS = { unresolved: 'Needs revision', fixed_with_guidance: 'Fixed with guidance', fixed_independently: 'Fixed independently' }
const EVIDENCE = { single_observation: 'single observation', suspected_recurring: 'suspected recurring weakness', supported_pattern: 'supported pattern' }
const pretty = (s) => s.replace(/_/g, ' ')
const tag = { fontSize: '11px', background: '#eef2ff', borderRadius: '4px', padding: '1px 6px', marginRight: '4px' }

function MistakeCard({ m, revision, onChanged }) {
  const [open, setOpen] = useState(false)
  const [revealed, setRevealed] = useState(false)
  const [extra, setExtra] = useState(null)
  const [busy, setBusy] = useState(false)
  const showAll = !revision && open

  const patch = async (p) => { await extApi.patchMistake(m.id, p); onChanged() }
  const remove = async () => {
    if (window.confirm('Delete this entry?')) { await extApi.deleteMistake(m.id); onChanged() }
  }
  const ask = async (mode) => {
    setBusy(true)
    try { setExtra((await extApi.explain(m.id, mode)).message) } catch (e) { setExtra(e.message) } finally { setBusy(false) }
  }

  return (
    <div style={{ border: '1px solid #ddd', borderRadius: '6px', padding: '8px', marginBottom: '8px' }}>
      <div onClick={() => !revision && setOpen(!open)} style={{ cursor: revision ? 'default' : 'pointer' }}>
        <strong>{m.problem_number ? `${m.problem_number}. ` : ''}{m.problem_title}</strong>
        <div style={{ marginTop: '4px' }}>
          <span style={tag}>{pretty(m.category)}</span>
          <span style={tag}>{STATUS[m.status]}</span>
          {m.is_hypothesis && <span style={tag}>hypothesis · {m.confidence}</span>}
          {m.marked_for_revision && <span style={tag}>marked</span>}
          {m.reviewed && <span style={tag}>reviewed</span>}
        </div>
        {!showAll && !revision && <div style={{ color: '#444', marginTop: '4px' }}>{m.what_went_wrong}</div>}
      </div>

      {revision && (
        <div style={{ marginTop: '6px' }}>
          <div><strong>Revision hint:</strong> {m.revision_hint}</div>
          {revealed && (
            <div style={{ marginTop: '6px' }}>
              <div><strong>What went wrong:</strong> {m.what_went_wrong}</div>
              <div><strong>Why (hypothesis):</strong> {m.why_happened}</div>
              <div><strong>Concept:</strong> {m.concept}</div>
            </div>
          )}
          <div style={{ marginTop: '6px', display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            {!revealed && <button onClick={() => setRevealed(true)}>Reveal explanation</button>}
            <button onClick={() => ask('hint')} disabled={busy}>Another hint</button>
            <button onClick={() => ask('practice')} disabled={busy}>Practice question</button>
          </div>
        </div>
      )}

      {showAll && (
        <div style={{ marginTop: '6px' }}>
          <div><strong>What went wrong:</strong> {m.what_went_wrong}</div>
          <div><strong>Why it happened{m.is_hypothesis ? ' (hypothesis)' : ''}:</strong> {m.why_happened}</div>
          <div><strong>Revision hint:</strong> {m.revision_hint}</div>
          <div><strong>Concept to revise:</strong> {m.concept}</div>
          <div style={{ color: '#666' }}><strong>Evidence:</strong> {m.evidence}</div>
          <div style={{ color: '#666' }}>Seen {m.occurrences}× · last {new Date(m.last_seen).toLocaleDateString()}</div>
          <div style={{ marginTop: '6px', display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            <button onClick={() => ask('hint')} disabled={busy}>Another Socratic hint</button>
            <button onClick={() => ask('practice')} disabled={busy}>Practice question</button>
          </div>
        </div>
      )}

      {extra && <div style={{ marginTop: '6px', background: '#f0f0f0', borderRadius: '6px', padding: '6px' }}>{extra}</div>}

      <div style={{ marginTop: '6px', display: 'flex', gap: '6px', flexWrap: 'wrap', fontSize: '12px' }}>
        {m.problem_url && <a href={m.problem_url} target="_blank" rel="noreferrer">Open on LeetCode</a>}
        <button onClick={() => patch({ reviewed: !m.reviewed })}>{m.reviewed ? 'Unmark reviewed' : 'Mark reviewed'}</button>
        <button onClick={() => patch({ marked_for_revision: !m.marked_for_revision })}>
          {m.marked_for_revision ? 'Unmark for revision' : 'Mark for revision'}
        </button>
        <button onClick={remove}>Delete</button>
      </div>
    </div>
  )
}

export default function MistakesPanel() {
  const [view, setView] = useState('recent')
  const [q, setQ] = useState('')
  const [category, setCategory] = useState('')
  const [revision, setRevision] = useState(false)
  const [items, setItems] = useState([])
  const [patterns, setPatterns] = useState([])
  const [summary, setSummary] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      if (view === 'patterns') setPatterns(await extApi.patterns())
      else if (view === 'summary') setSummary(await extApi.summary())
      else setItems(await extApi.mistakes({ view, q: q.trim(), category }))
    } catch (e) { setError(e.message) }
  }, [view, q, category])
  useEffect(() => { load() }, [load])

  const list = view !== 'patterns' && view !== 'summary'
  return (
    <div>
      <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginBottom: '8px' }}>
        {VIEWS.map(([id, label]) => (
          <button key={id} onClick={() => setView(id)} style={{ fontWeight: view === id ? 700 : 400 }}>{label}</button>
        ))}
      </div>

      {list && (
        <div style={{ display: 'flex', gap: '6px', marginBottom: '8px', flexWrap: 'wrap' }}>
          <input placeholder="Search title, number, category…" value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: 1, minWidth: '140px' }} />
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All categories</option>
            {CATEGORIES.map((c) => <option key={c} value={c}>{pretty(c)}</option>)}
          </select>
          <label style={{ fontSize: '12px' }}>
            <input type="checkbox" checked={revision} onChange={(e) => setRevision(e.target.checked)} /> Revision mode
          </label>
        </div>
      )}

      {error && <p style={{ color: '#b91c1c' }}>{error}</p>}

      {list && items.length === 0 && !error && (
        <p style={{ color: '#666' }}>Nothing here yet. Entries appear after a failed submission is analyzed with enough evidence.</p>
      )}
      {list && items.map((m) => <MistakeCard key={m.id} m={m} revision={revision} onChanged={load} />)}

      {view === 'patterns' && (
        <>
          <p style={{ color: '#666' }}>
            Patterns show where mistakes were observed across different problems. They are evidence about habits, not a
            measure of ability.
          </p>
          {patterns.length === 0 && <p style={{ color: '#666' }}>No patterns yet.</p>}
          {patterns.map((p) => (
            <div key={p.category} style={{ border: '1px solid #ddd', borderRadius: '6px', padding: '8px', marginBottom: '8px' }}>
              <strong>{pretty(p.category)}</strong> <span style={tag}>{EVIDENCE[p.evidence_level]}</span>
              <div>Seen on {p.distinct_problems} problem(s) · trend: {pretty(p.trend)}</div>
              <div style={{ color: '#666' }}>
                {p.unresolved} unresolved · {p.fixed_with_guidance} fixed with guidance · {p.fixed_independently} fixed independently
              </div>
              <div style={{ color: '#666' }}>Concepts: {p.concepts.join(', ')}</div>
            </div>
          ))}
        </>
      )}

      {view === 'summary' && summary && (
        <div>
          <p>
            Problems attempted: <strong>{summary.problems_attempted}</strong> · solved (verified): <strong>{summary.problems_solved}</strong> ·
            observations recorded: <strong>{summary.total_observations}</strong>
          </p>
          {Object.entries(summary.by_category).map(([c, n]) => (
            <div key={c} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ width: '140px' }}>{pretty(c)}</span>
              <div style={{ background: '#2563eb', height: '10px', width: `${Math.min(100, n * 20)}px` }} />
              <span>{n}</span>
            </div>
          ))}
          <h4>By status</h4>
          {Object.entries(summary.by_status).map(([s, n]) => <div key={s}>{STATUS[s]}: {n}</div>)}
          <h4>Last weeks</h4>
          {summary.weekly.length === 0 && <div style={{ color: '#666' }}>No data yet.</div>}
          {summary.weekly.map((w) => (
            <div key={w.week}>Week of {w.week}: {w.observed} observed · {w.fixed_independently} fixed independently · {w.fixed_with_guidance} with guidance</div>
          ))}
        </div>
      )}
    </div>
  )
}
