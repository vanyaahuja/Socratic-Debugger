/**
 * Page-context adapter. The ONLY place that knows how a LeetCode page is laid out.
 *
 * It is injected with chrome.scripting.executeScript({ world: 'MAIN', func }) only
 * when the student presses a button, so it must be fully self-contained (the
 * function is serialized into the page: no imports, no references to outer scope).
 *
 * What it reads (and nothing else): problem title/number/difficulty, the problem
 * description, the editor's text, the language, and the visible submission/run
 * result panel. It does not touch cookies, storage, network, or other page
 * content, and it never calls LeetCode's internal APIs.
 *
 * IMPORTANT -- UNVERIFIED AGAINST LIVE PAGES: LeetCode has no supported extension
 * API and its markup changes. Every selector below is a best-effort guess,
 * ordered most- to least-specific, and every miss is reported in `missing`
 * instead of being guessed around. If LeetCode changes its layout, this is the
 * only function to update.
 */
export function collectLeetCodeContext() {
  const out = {
    ok: true,
    problem: {},
    language: null,
    code: null,
    submission: { status: 'unknown', source: 'none', kind: 'none', message: null, testcases_passed: null, testcases_total: null },
    missing: [],
    notes: [],
  }
  const text = (el) => ((el && (el.innerText || el.textContent)) || '').trim()
  const first = (selectors) => {
    for (const s of selectors) {
      try {
        const el = document.querySelector(s)
        if (el) return el
      } catch (e) { /* invalid selector: try next */ }
    }
    return null
  }

  // --- which problem is this? (the URL is the only reliable source) ---
  const m = location.pathname.match(/^\/problems\/([a-z0-9-]+)/)
  if (!m) {
    out.ok = false
    out.missing.push('problem_page')
    return out
  }
  const slug = m[1]
  out.problem.slug = slug
  out.problem.url = 'https://leetcode.com/problems/' + slug + '/'

  // --- title / number / difficulty ---
  try {
    const titleEl = first(['[data-cy="question-title"]', 'div[class*="text-title-large"] a', 'a[href^="/problems/' + slug + '"]'])
    const raw = text(titleEl) || document.title.replace(/\s*-\s*LeetCode.*$/i, '').trim()
    const num = raw.match(/^(\d+)\.\s*(.+)$/)
    if (num) {
      out.problem.frontend_id = num[1]
      out.problem.title = num[2]
    } else if (raw) {
      out.problem.title = raw
    }
    const diff = first(['div[class*="text-difficulty-easy"]', 'div[class*="text-difficulty-medium"]', 'div[class*="text-difficulty-hard"]'])
    if (diff) out.problem.difficulty = text(diff).toLowerCase().slice(0, 20)
  } catch (e) { /* reported below */ }
  if (!out.problem.title) out.missing.push('problem_title')

  // --- statement (only the description container, never the whole page) ---
  let statement = ''
  try {
    statement = text(first(['[data-track-load="description_content"]', 'div[class*="elfjS"]']))
    if (!statement) {
      const meta = document.querySelector('meta[name="description"]')
      statement = meta ? (meta.getAttribute('content') || '') : ''
      if (statement) out.notes.push('statement taken from the page meta description (LeetCode truncates it)')
    }
  } catch (e) { /* reported below */ }
  if (!statement) out.missing.push('problem_statement')
  out.problem.statement = statement.slice(0, 8000)

  // --- editor contents + language ---
  let code = null
  let lang = null
  try {
    const mon = window.monaco && window.monaco.editor
    if (mon) {
      const editors = mon.getEditors ? mon.getEditors() : []
      const model = (editors[0] && editors[0].getModel && editors[0].getModel()) ||
        (mon.getModels && mon.getModels()[0])
      if (model) {
        code = model.getValue()
        lang = model.getLanguageId ? model.getLanguageId() : (model.getModeId ? model.getModeId() : null)
      }
    }
  } catch (e) { /* fall through to DOM */ }
  if (!code) {
    // Fallback: only the lines the editor has rendered (it virtualizes long files).
    const lines = Array.from(document.querySelectorAll('.monaco-editor .view-lines .view-line'))
    if (lines.length) {
      lines.sort((a, b) => (parseInt(a.style.top, 10) || 0) - (parseInt(b.style.top, 10) || 0))
      code = lines.map((l) => l.textContent).join('\n')
      out.notes.push('code read from the visible editor lines only; very long files may be incomplete')
    }
  }
  if (code) out.code = code.replace(/\u00a0/g, ' ').slice(0, 20000)
  else out.missing.push('editor_code')

  if (!lang) {
    const btn = first(['[data-cy="lang-select"]', 'button[aria-haspopup="listbox"]'])
    lang = btn ? text(btn).split('\n')[0].trim() : null
  }
  if (lang) out.language = lang.toLowerCase().slice(0, 40)
  else out.missing.push('language')

  // --- latest result: a real submission, or just a run on the sample cases ---
  const mapStatus = (t) => {
    const s = (t || '').toLowerCase()
    if (s.includes('wrong answer')) return 'wrong_answer'
    if (s.includes('accepted')) return 'accepted'
    if (s.includes('runtime error')) return 'runtime_error'
    if (s.includes('compile error')) return 'compile_error'
    if (s.includes('time limit')) return 'time_limit_exceeded'
    if (s.includes('memory limit')) return 'memory_limit_exceeded'
    if (s.includes('judging') || s.includes('running') || s.includes('pending')) return 'running'
    return 'unknown'
  }
  try {
    const subEl = first(['[data-e2e-locator="submission-result"]'])
    const runEl = subEl ? null : first(['[data-e2e-locator="console-result"]'])
    const el = subEl || runEl
    if (el) {
      const status = mapStatus(text(el))
      const panel = (el.parentElement && el.parentElement.parentElement) || el.parentElement || el
      const panelText = text(panel).slice(0, 1500)
      const tc = panelText.match(/(\d+)\s*\/\s*(\d+)\s*testcases?\s*passed/i)
      out.submission = {
        // A run that passes the samples is NOT an Accepted submission.
        status: runEl && status === 'accepted' ? 'run_passed' : status,
        source: 'page',
        kind: subEl ? 'submit' : 'run',
        message: panelText || null,
        testcases_passed: tc ? parseInt(tc[1], 10) : null,
        testcases_total: tc ? parseInt(tc[2], 10) : null,
      }
    } else {
      out.missing.push('submission_result')
    }
  } catch (e) {
    out.missing.push('submission_result')
  }
  return out
}
