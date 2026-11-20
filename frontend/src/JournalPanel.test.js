import test, { before, after, afterEach } from 'node:test'
import assert from 'node:assert/strict'
import React, { act } from 'react'
import { JSDOM } from 'jsdom'
import { createServer } from 'vite'

let dom, server, Panel, useTheme, api, createRoot, Simulate, root, store
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
  api.journal = async () => [{ ...sample, how_found: '', how_fixed: '', takeaway: '', outcome: 'in_progress' }]
  await mount()
  assert.match(document.body.textContent, /Set Mismatch/)
  assert.match(document.body.textContent, /Pending: analyze the changed code/)
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
