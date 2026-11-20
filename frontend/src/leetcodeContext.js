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
  const text = (el) => {
    if (!el) return ''
    if (typeof el.innerText === 'string') return el.innerText.trim()
    // Preserve field boundaries even in DOM implementations without innerText.
    const walk = (node) => {
      if (node.nodeType === 3) return node.textContent || ''
      if (node.nodeType !== 1) return ''
      if (node.hidden || node.getAttribute('aria-hidden') === 'true' || node.style.display === 'none') return ''
      if (node.tagName === 'BR') return '\n'
      const value = Array.from(node.childNodes).map(walk).join('')
      return /^(DIV|SECTION|P|PRE|H[1-6]|DT|DD|LI|TR)$/.test(node.tagName) ? '\n' + value + '\n' : value
    }
    return walk(el).replace(/\n{3,}/g, '\n\n').trim()
  }
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

  // --- visible result: markers first, then scoped panel/heading fallbacks ---
  // Helpers stay inside this function: Chrome serializes it without imports.
  const visible = (el) => {
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      if (node.hidden || node.getAttribute('aria-hidden') === 'true') return false
      const style = window.getComputedStyle(node)
      if (style.display === 'none' || style.visibility === 'hidden') return false
    }
    return true
  }
  const statuses = new Map([
    ['wrong answer', 'wrong_answer'], ['accepted', 'accepted'],
    ['runtime error', 'runtime_error'], ['compile error', 'compile_error'],
    ['time limit exceeded', 'time_limit_exceeded'], ['memory limit exceeded', 'memory_limit_exceeded'],
    ['judging', 'running'], ['running', 'running'], ['pending', 'running'],
  ])
  const statusOf = (value) => statuses.get(value.trim().replace(/\s+/g, ' ').toLowerCase()) || 'unknown'
  const countsOf = (value) => value.match(/(\d+)\s*\/\s*(\d+)\s*(?:test\s*cases?|testcases?)\s*passed/i)
  const fieldCount = (value) => ['input', 'output', 'expected'].filter((label) =>
    new RegExp('(?:^|\\n)\\s*(?:last executed )?' + label + '\\s*(?::|\\n|$)', 'i').test(value)).length
  const excluded = (el) => el.closest('[data-track-load="description_content"], [data-cy="question-title"], .monaco-editor, nav, [role="navigation"]')
  const panelName = (panel) => {
    let name = panel.getAttribute('aria-label') || ''
    for (const id of (panel.getAttribute('aria-labelledby') || '').split(/\s+/)) {
      if (id) name += ' ' + text(document.getElementById(id))
    }
    for (const tab of document.querySelectorAll('[role="tab"][aria-controls]')) {
      if (panel.id && tab.getAttribute('aria-controls') === panel.id) name += ' ' + text(tab)
    }
    return name.trim()
  }
  const kindOf = (panel) => {
    const name = panelName(panel)
    if (/submission|submit result/i.test(name)) return 'submit'
    if (/test result|run result/i.test(name)) return 'run'
    if (/\/submissions\/\d+(?:\/|$)/.test(location.pathname)) return 'submit'
    return 'none' // An ambiguous Accepted never verifies a full submission.
  }
  const findStatus = (panel) => {
    if (visible(panel) && statusOf(text(panel)) !== 'unknown') return panel
    return Array.from(panel.querySelectorAll('span, div, h1, h2, h3, p, strong'))
      .find((el) => !excluded(el) && visible(el) && statusOf(text(el)) !== 'unknown')
  }
  const surroundingPanel = (statusEl) => {
    let best = statusEl
    let score = -1
    for (let node = statusEl, depth = 0; node && depth < 9; node = node.parentElement, depth++) {
      if (node === document.body || node === document.documentElement || excluded(node)) break
      if (node.querySelector('[data-track-load="description_content"], .monaco-editor')) break
      const value = text(node)
      if (value.length > 12000) break
      const fields = fieldCount(value)
      const nextScore = fields * 2 + (countsOf(value) ? 1 : 0)
      if (nextScore > score || (score === 0 && best === statusEl
          && value.length > text(statusEl).length && value.length <= 4000)) {
        best = node; score = nextScore
      }
      if (fields === 3) break
    }
    return best
  }
  try {
    let found = null
    // Known markers identify Run vs Submit without treating sample success as solved.
    for (const [selector, kind] of [
      ['[data-e2e-locator="submission-result"]', 'submit'],
      ['[data-cy="submission-result"]', 'submit'],
      ['[data-e2e-locator="console-result"]', 'run'],
      ['[data-cy="run-result"]', 'run'],
    ]) {
      const marker = Array.from(document.querySelectorAll(selector)).find(visible)
      const heading = marker && findStatus(marker)
      if (heading) { found = { heading, panel: surroundingPanel(heading), kind }; break }
    }
    // Accessibility-labelled result panels survive changes to CSS class names.
    if (!found) {
      for (const panel of document.querySelectorAll('[role="tabpanel"], [aria-label]')) {
        if (!visible(panel) || excluded(panel) || !/submission|test result|run result/i.test(panelName(panel))) continue
        const heading = findStatus(panel)
        if (heading) { found = { heading, panel: surroundingPanel(heading), kind: kindOf(panel) }; break }
      }
    }
    // Some layouts have no result marker. Only accept a compact, exact status
    // heading near case counts or input/output fields; never search body text.
    if (!found) {
      const headings = document.querySelectorAll('span, div, h1, h2, h3, p, strong')
      for (const heading of headings) {
        if (excluded(heading) || !visible(heading) || statusOf(text(heading)) === 'unknown') continue
        const panel = surroundingPanel(heading)
        const value = text(panel)
        if (!countsOf(value) && fieldCount(value) < 2) continue
        found = { heading, panel, kind: kindOf(panel) }
        break
      }
    }
    if (found) {
      const panelText = text(found.panel)
      const tc = countsOf(panelText)
      let status = statusOf(text(found.heading))
      if (status === 'accepted' && found.kind === 'run') status = 'run_passed'
      out.submission = {
        status, source: 'page', kind: found.kind,
        // Keep verdict, count and field labels/values. Clip each evidence block
        // separately so a long failing input cannot remove Output and Expected.
        message: (() => {
          const chunks = [text(found.heading)]
          if (tc) chunks.push(tc[0])
          const sections = panelText.split(/(?:^|\n)\s*(Last Executed Input|Input|Output|Expected)\s*(?::\s*|\n|$)/i)
          for (let i = 1; i + 1 < sections.length; i += 2) {
            chunks.push(sections[i] + ': ' + sections[i + 1].trim().slice(0, 500))
          }
          return (chunks.length > (tc ? 2 : 1) ? chunks.join('\n') : panelText).slice(0, 2000)
        })(),
        testcases_passed: tc ? Number(tc[1]) : null,
        testcases_total: tc ? Number(tc[2]) : null,
      }
      if (found.kind === 'none') out.notes.push('Result found, but Run vs Submit is unclear; Accepted cannot be verified.')
      if (status === 'wrong_answer' && fieldCount(panelText) < 3) {
        out.notes.push('Wrong Answer was read, but some failing input/output details are not visible. Expand the failing case on LeetCode and analyze again.')
      }
    } else {
      out.missing.push('submission_result')
    }
  } catch (e) {
    out.missing.push('submission_result')
  }
  return out
}
