import test from 'node:test'
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'
import { collectLeetCodeContext } from './leetcodeContext.js'

function collect(result, { url = 'https://leetcode.com/problems/set-mismatch/', extra = '' } = {}) {
  const dom = new JSDOM(`<main>
    <div data-cy="question-title">645. Set Mismatch</div>
    <div data-track-load="description_content">Find the duplicate and missing number. ${extra}</div>
    ${result}
  </main>`, { url, runScripts: 'outside-only' })
  dom.window.monaco = { editor: { getEditors: () => [{ getModel: () => ({
    getValue: () => 'return [1, 2]', getLanguageId: () => 'python3',
  }) }] } }
  // Mirrors executeScript serialization: no imported helper may be referenced.
  const context = JSON.parse(JSON.stringify(dom.window.eval(`(${collectLeetCodeContext.toString()})()`)))
  dom.window.close()
  return context
}

const details = `
  <div>43 / 50 testcases passed</div>
  <div>Input\nnums = [2,2]</div>
  <div>Output\n[1,2]</div>
  <div>Expected\n[2,1]</div>
`

test('reads Wrong Answer, counts, failing input and expected/actual from a marked result', () => {
  const c = collect(`<section><span data-e2e-locator="submission-result">Wrong Answer</span>${details}</section>`)
  assert.equal(c.submission.status, 'wrong_answer')
  assert.equal(c.submission.kind, 'submit')
  assert.equal(c.submission.testcases_passed, 43)
  assert.equal(c.submission.testcases_total, 50)
  assert.match(c.submission.message, /Input: nums = \[2,2\]/)
  assert.match(c.submission.message, /Output: \[1,2\]/)
  assert.match(c.submission.message, /Expected: \[2,1\]/)
  assert.ok(!c.submission.message.includes('Find the duplicate'))
})

test('reads an accessible submission panel without the old locator', () => {
  const c = collect(`<button role="tab" id="result-tab" aria-controls="result-panel">Submission Result</button>
    <section role="tabpanel" id="result-panel" aria-labelledby="result-tab"><h2>Wrong Answer</h2>${details}</section>`)
  assert.equal(c.submission.kind, 'submit')
  assert.equal(c.submission.status, 'wrong_answer')
})

test('unmarked compact result still collects failure evidence without guessing Submit', () => {
  const c = collect(`<section><h2>Wrong Answer</h2>${details}</section>`)
  assert.equal(c.submission.status, 'wrong_answer')
  assert.equal(c.submission.kind, 'none')
  assert.equal(c.submission.testcases_passed, 43)
})

test('submission detail URL identifies an otherwise unmarked result', () => {
  const c = collect(`<section><h2>Wrong Answer</h2>${details}</section>`, {
    url: 'https://leetcode.com/problems/set-mismatch/submissions/12345/',
  })
  assert.equal(c.submission.kind, 'submit')
})

test('a sample Accepted remains run_passed', () => {
  const c = collect('<section role="tabpanel" aria-label="Test Result"><h2>Accepted</h2><div>3 / 3 testcases passed</div></section>')
  assert.equal(c.submission.status, 'run_passed')
  assert.equal(c.submission.kind, 'run')
})

test('ambiguous Accepted cannot verify a full submission', () => {
  const c = collect('<section><h2>Accepted</h2><div>3 / 3 testcases passed</div></section>')
  assert.equal(c.submission.kind, 'none')
})

test('ignores hidden stale results and verdict-looking problem text', () => {
  const c = collect(`<section style="display:none"><span data-e2e-locator="submission-result">Accepted</span></section>
    <section><h2>Wrong Answer</h2>${details}</section>`, { extra: '<h2>Accepted</h2><div>99 / 99 testcases passed</div>' })
  assert.equal(c.submission.status, 'wrong_answer')
  assert.equal(c.submission.testcases_passed, 43)
})

test('does not mistake ordinary discussion of a verdict for a result', () => {
  const c = collect('<aside>My code gave Wrong Answer yesterday.</aside>')
  assert.equal(c.submission.status, 'unknown')
  assert.ok(c.missing.includes('submission_result'))
})

test('keeps zero passed and includes output/expected after a long input', () => {
  const long = `<section><span data-e2e-locator="submission-result">Wrong Answer</span>
    <div>0 / 50 test cases passed</div><div>Last Executed Input\n${'9,'.repeat(1200)}</div>
    <div>Output\n[1,2]</div><div>Expected\n[2,1]</div></section>`
  const c = collect(long)
  assert.equal(c.submission.testcases_passed, 0)
  assert.ok(c.submission.message.length <= 2000)
  assert.match(c.submission.message, /Expected: \[2,1\]/)
})

test('compile error retains the adjacent compiler feedback without input/output fields', () => {
  const c = collect('<section><span data-e2e-locator="submission-result">Compile Error</span><pre>Line 12: expected semicolon</pre></section>')
  assert.equal(c.submission.status, 'compile_error')
  assert.match(c.submission.message, /expected semicolon/)
})
