import { useEffect, useRef, useState } from 'react'
import { extApi } from './api/client'
import MistakesPanel from './MistakesPanel'

const outcome = { in_progress: 'In progress', verified_accepted: 'Accepted · verified', user_reported: 'Solved · self-reported' }

export function JournalCard({ entry, revision, onSaved }) {
  const [reveal, setReveal] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(entry)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { if (!editing) setDraft(entry) }, [entry, editing])
  const save = async (patch) => {
    setBusy(true); setError('')
    try { onSaved(await extApi.patchJournal(entry.id, patch)); setEditing(false) }
    catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }
  return <article className="journal-card">
    <div className="eyebrow">REVISION NOTE</div>
    <h3>{entry.problem_title}</h3>
    <div className="badges"><span className={`badge ${entry.outcome === 'verified_accepted' ? 'success' : ''}`}>{outcome[entry.outcome]}</span>
      <span className="badge">{entry.edited ? 'Edited by you' : entry.how_found || entry.how_fixed ? 'AI-inferred · check the explanation' : 'Notes pending'}</span>
      {entry.reviewed && <span className="badge">Reviewed</span>}</div>
    {editing ? <div className="journal-editor">
      {['how_found', 'how_fixed', 'takeaway'].map((field, i) => <label key={field}>{['How I found it', 'How I fixed it', 'Remember next time'][i]}
        <textarea value={draft[field]} maxLength={field === 'takeaway' ? 400 : 600} onChange={(e) => setDraft({ ...draft, [field]: e.target.value })} />
      </label>)}
      <div className="button-row"><button className="primary" disabled={busy} onClick={() => save({ how_found: draft.how_found, how_fixed: draft.how_fixed, takeaway: draft.takeaway })}>Save notes</button>
        <button disabled={busy} onClick={() => setEditing(false)}>Cancel</button></div>
    </div> : <>
      <div className="note-section"><h4>How I found it</h4><p>{entry.how_found || 'A draft is saved. Analyze a failing version to help identify the clue.'}</p></div>
      {(!revision || reveal) ? <>
        <div className="note-section"><h4>How I fixed it</h4><p>{entry.how_fixed || 'Pending: analyze the changed code after solving. An earlier code version is needed to infer the fix.'}</p></div>
        <div className="note-section"><h4>How I checked it</h4><p>{entry.outcome === 'verified_accepted' ? 'LeetCode showed an Accepted submission.' : entry.outcome === 'user_reported' ? 'You reported it solved. Acceptance has not been read from the page.' : 'Not verified yet. Submit the changed code, then analyze the visible result.'}</p></div>
        <div className="takeaway"><h4>Remember next time</h4><p>{entry.takeaway || 'Your takeaway will appear when there is enough evidence.'}</p></div>
      </> : <button className="reveal-button" onClick={() => setReveal(true)}>Try recalling the fix, then reveal →</button>}
      <div className="card-actions">
        {entry.problem_url?.startsWith('https://leetcode.com/problems/') && <a href={entry.problem_url} target="_blank" rel="noreferrer">Open problem ↗</a>}
        <button disabled={busy} onClick={() => save({ reviewed: !entry.reviewed })}>{entry.reviewed ? 'Unmark reviewed' : 'Mark reviewed'}</button>
        <button onClick={() => setEditing(true)}>Edit notes</button>
      </div>
    </>}
    {error && <p className="notice error" role="alert">{error}</p>}
  </article>
}

export default function JournalPanel() {
  const [entries, setEntries] = useState([])
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [revision, setRevision] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const request = useRef(0)
  const load = async () => {
    const id = ++request.current
    setLoading(true); setError('')
    try { const rows = await extApi.journal(); if (id === request.current) setEntries(rows) }
    catch (e) { if (id === request.current) setError(e.message) }
    finally { if (id === request.current) setLoading(false) }
  }
  useEffect(() => { load(); return () => { request.current++ } }, [])
  const shown = entries.filter((e) => (filter !== 'review' || !e.reviewed) &&
    (filter !== 'solved' || e.outcome !== 'in_progress') &&
    `${e.problem_title} ${e.how_found} ${e.how_fixed} ${e.takeaway}`.toLowerCase().includes(search.toLowerCase()))
  const saved = (entry) => setEntries((all) => all.map((e) => e.id === entry.id ? entry : e))
  const exportNotes = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(entries, null, 2)], { type: 'application/json' }))
    const a = document.createElement('a'); a.href = url; a.download = 'socratic-revision-notes.json'; a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return <section className="journal-panel">
    <div className="section-heading"><div><div className="eyebrow">YOUR LEARNING, KEPT</div><h2>My mistakes</h2></div><button onClick={load} disabled={loading} aria-label="Refresh revision journal">↻</button></div>
    <p className="muted intro">The clue, the change, the lesson. Simple notes to revisit before your next problem.</p>
    <div className="filter-tabs">{[['all', 'All problems'], ['review', 'To revise'], ['solved', 'Solved'], ['legacy', 'Earlier records']].map(([id, label]) =>
      <button key={id} aria-pressed={filter === id} className={filter === id ? 'selected' : ''} onClick={() => setFilter(id)}>{label}</button>)}</div>
    {filter === 'legacy' ? <MistakesPanel /> : <>
      <input className="search" aria-label="Search revision notes" placeholder="Search a problem or lesson…" value={search} onChange={(e) => setSearch(e.target.value)} />
      <div className="journal-toolbar"><label className="checkbox"><input type="checkbox" checked={revision} onChange={(e) => setRevision(e.target.checked)} /> Recall before reveal</label>
        <button onClick={exportNotes} disabled={!entries.length}>Export</button></div>
      {loading ? <p className="muted" role="status">Loading your notes…</p> : error ? <div className="notice error" role="alert">{error}<button onClick={load}>Retry</button></div>
        : shown.length ? shown.map((entry) => <JournalCard key={`${entry.id}-${revision}`} entry={entry} revision={revision} onSaved={saved} />)
          : <div className="empty-state"><div className="empty-symbol">↗</div><h3>{entries.length ? 'No matching notes' : 'Your next lesson starts here'}</h3><p>{entries.length ? 'Try another search or filter.' : 'Analyze a problem in Tutor. A draft is saved first; the explanation grows as you debug.'}</p></div>}
    </>}
  </section>
}
