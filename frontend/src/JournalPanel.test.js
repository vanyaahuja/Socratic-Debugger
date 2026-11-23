import test, { before, after, afterEach } from 'node:test'
import assert from 'node:assert/strict'
import React, { act } from 'react'
import { JSDOM } from 'jsdom'
import { createServer } from 'vite'

let dom, server, Panel, Extension, useTheme, api, createRoot, Simulate, root, store
const sample = { id: 1, problem_title: 'Set Mismatch', problem_url: 'https://leetcode.com/problems/set-mismatch/',
  how_found: 'The values were right, but their order was wrong.', how_fixed: 'Kept each value separate, then put the duplicate first.',
  takeaway: 'Check the required output order.', outcome: 'verified_accepted', edited: false, uncertain: true, reviewed: false }
before(async () => {
  dom = new JSDOM('<div id="test-root"></div>', { url: 'http://localhost/' })
  globalThis.window = dom.window; globalThis.document = dom.window.document
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  ;({ createRoot } = await import('react-dom/client'))
  ;({ Simulate } = await import('react-dom/test-utils'))
  server = await createServer({ server: { middlewareMode: true, watch: null, ws: false }, appType: 'custom' })
  Panel = (await server.ssrLoadModule('/src/JournalPanel.jsx')).default
  Extension = (await server.ssrLoadModule('/src/ExtensionApp.jsx')).default
  api = (await server.ssrLoadModule('/src/api/client.js')).extApi
  useTheme = (await server.ssrLoadModule('/src/useTheme.js')).default
})
afterEach(() => { if (root) act(() => root.unmount()); root = null })
after(async () => { await server?.close(); dom?.window.close(); delete globalThis.window; delete globalThis.document; delete globalThis.chrome })
async function mount(Component = Panel) {
  root = createRoot(document.getElementById('test-root'))
  await act(async () => root.render(React.createElement(Component)))
}
const button = (label) => Array.from(document.querySelectorAll('button')).find((b) => b.textContent === label)

test('renders code-free explanation and labelled verification', async () => {
  api.journal = async () => [sample]
  await mount()
  assert.match(document.body.textContent, /How I fixed it/)
  assert.match(document.body.textContent, /duplicate first/)
  assert.match(document.body.textContent, /AI-inferred/)
  assert.match(document.body.textContent, /Accepted · verified/)
})

test('draft entries remain visible with pending fix instead of an empty list', async () => {
  api.journal = async () => [{ ...sample, how_found: '', how_fixed: '', takeaway: '', outcome: 'in_progress', can_generate: true,
    pending_reason: 'The tutor replied without revision notes. Saved code is available.' }]
  await mount()
  assert.match(document.body.textContent, /Set Mismatch/)
  assert.match(document.body.textContent, /tutor replied without revision notes/)
  assert.ok(button('Generate notes'))
})

test('Generate notes repairs an existing blank entry', async () => {
  let row = { ...sample, how_found: '', how_fixed: '', takeaway: '', can_generate: true }
  let calls = 0
  api.journal = async () => [row]
  api.generateJournal = async (id) => { calls++; assert.equal(id, 1); row = { ...sample, can_generate: false }; return row }
  await mount()
  const generate = button('Generate notes')
  await act(async () => { Simulate.click(generate); Simulate.click(generate) })
  assert.equal(calls, 1)
  assert.match(document.body.textContent, /duplicate first/)
  assert.equal(button('Generate notes'), undefined)
})

test('Generate notes failure keeps the entry and shows an actionable error', async () => {
  api.journal = async () => [{ ...sample, how_found: '', how_fixed: '', takeaway: '', can_generate: true }]
  api.generateJournal = async () => { throw new Error('Provider usage limit reached. Try later.') }
  await mount()
  await act(async () => Simulate.click(button('Generate notes')))
  assert.match(document.querySelector('[role="alert"]').textContent, /usage limit/)
  assert.equal(button('Generate notes').disabled, false)
})

test('missing baseline explains the limitation instead of offering unsupported generation', async () => {
  api.journal = async () => [{ ...sample, how_found: '', how_fixed: '', takeaway: '', can_generate: false,
    pending_reason: 'A different earlier version is missing. The fix cannot be inferred from accepted code alone.' }]
  await mount()
  assert.match(document.body.textContent, /earlier version is missing/)
  assert.equal(button('Generate notes'), undefined)
})

test('accepted analysis automatically requests missing notes without blocking chat', async () => {
  const event = { addListener() {}, removeListener() {} }
  globalThis.chrome = {
    storage: { local: { get: async () => ({}), set: async () => {} } },
    tabs: { query: async () => [{ id: 1, url: 'https://leetcode.com/problems/binary-search/' }], onActivated: event, onUpdated: event },
    windows: { onFocusChanged: event }, scripting: { executeScript: async () => [{ frameId: 0, result: {
      ok: true, problem: { slug: 'binary-search', title: 'Binary Search' }, code: 'corrected version', language: 'python3',
      submission: { status: 'accepted', source: 'page', kind: 'submit' }, missing: [],
    } }] },
  }
  api.sessionBySlug = async () => null
  api.analyze = async () => ({ session_id: 1, state: 'SOLVED', verification: 'verified_accepted',
    journal_id: 1, journal_needs_generation: true,
    tutor: { message: 'Your submission was accepted.', response_type: 'question', reasoning_stage: 'reflect' } })
  let finish, calls = 0
  api.generateJournal = (id) => { calls++; assert.equal(id, 1); return new Promise((resolve) => { finish = resolve }) }
  await mount(Extension)
  await act(async () => Simulate.click(document.querySelector('button.analyze')))
  assert.equal(calls, 1)
  assert.match(document.body.textContent, /Your submission was accepted/)
  assert.ok(document.querySelector('textarea'))
  await act(async () => finish(sample))
  assert.match(document.body.textContent, /Revision notes saved in My Mistakes/)
})

test('revision mode hides the fix until reveal', async () => {
  api.journal = async () => [sample]
  await mount()
  act(() => Simulate.change(document.querySelector('input[type="checkbox"]'), { target: { checked: true } }))
  assert.ok(!document.body.textContent.includes(sample.how_fixed))
  act(() => Simulate.click(button('Try recalling the fix, then reveal →')))
  assert.ok(document.body.textContent.includes(sample.how_fixed))
})

test('edited notes are saved through the journal API', async () => {
  api.journal = async () => [sample]
  let saved
  api.patchJournal = async (id, patch) => { saved = patch; return { ...sample, ...patch, edited: true } }
  await mount()
  act(() => Simulate.click(button('Edit notes')))
  act(() => Simulate.change(document.querySelectorAll('textarea')[1], { target: { value: 'I put the duplicate first.' } }))
  await act(async () => Simulate.click(button('Save notes')))
  assert.equal(saved.how_fixed, 'I put the duplicate first.')
  assert.match(document.body.textContent, /Edited by you/)
})

test('loading failures show an error and retry instead of an empty journal', async () => {
  api.journal = async () => { throw new Error('Backend offline') }
  await mount()
  assert.match(document.querySelector('[role="alert"]').textContent, /Backend offline/)
  assert.ok(button('Retry'))
})

test('theme preference loads, toggles and persists across remount', async () => {
  store = { theme: 'dark' }
  globalThis.chrome = { storage: { local: { get: async () => ({ ...store }), set: async (value) => Object.assign(store, value) } } }
  function ThemeHarness() { const [theme, toggle] = useTheme(); return React.createElement('button', { onClick: toggle, 'data-theme': theme }, 'Toggle theme') }
  await mount(ThemeHarness)
  assert.equal(button('Toggle theme').dataset.theme, 'dark')
  await act(async () => Simulate.click(button('Toggle theme')))
  assert.equal(store.theme, 'light')
  act(() => root.unmount()); root = null
  await mount(ThemeHarness)
  assert.equal(button('Toggle theme').dataset.theme, 'light')
})
