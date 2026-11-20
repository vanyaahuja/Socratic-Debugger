import test, { before, after, afterEach } from 'node:test'
import assert from 'node:assert/strict'
import React, { act } from 'react'
import { JSDOM } from 'jsdom'
import { createServer } from 'vite'

let server, dom, Component, createRoot, Simulate, root
before(async () => {
  dom = new JSDOM('<div id="test-root"></div>', { url: 'http://localhost/' })
  globalThis.window = dom.window
  globalThis.document = dom.window.document
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  ;({ createRoot } = await import('react-dom/client'))
  ;({ Simulate } = await import('react-dom/test-utils'))
  server = await createServer({ server: { middlewareMode: true, watch: null }, appType: 'custom' })
  Component = (await server.ssrLoadModule('/src/components/TutorChat.jsx')).default
})
afterEach(() => {
  if (root) act(() => root.unmount())
  root = null
})
after(async () => {
  await server?.close()
  dom?.window.close()
  delete globalThis.window
  delete globalThis.document
})

function render(overrides = {}) {
  const props = {
    messages: [{ from: 'tutor', text: 'What is the complexity?', responseType: 'question', reasoningStage: 'resolved' }],
    onRequestHint: () => {}, onSubmitReasoning: async () => true, waiting: false, canRequestHint: true,
    ...overrides,
  }
  if (!root) root = createRoot(document.getElementById('test-root'))
  act(() => root.render(React.createElement(Component, props)))
  return document.querySelector('textarea')
}
function type(input, value) {
  act(() => Simulate.change(input, { target: { value } }))
}
function key(input, extras = {}) {
  Simulate.keyDown(input, { key: 'Enter', nativeEvent: {}, ...extras })
}

test('resolved and instruction turns retain the reply box', () => {
  assert.ok(render())
  assert.ok(render({ messages: [{ from: 'tutor', text: 'Try it.', responseType: 'instruction', reasoningStage: 'implement_fix' }] }))
})

test('Enter sends the reply once and clears a successful draft', async () => {
  const sent = []
  const input = render({ onSubmitReasoning: async (value) => { sent.push(value); return true } })
  type(input, 'O(n) space')
  await act(async () => { key(input); key(input) })
  assert.deepEqual(sent, ['O(n) space'])
  assert.equal(input.value, '')
})

test('Shift+Enter and input-method composition do not send', async () => {
  let count = 0
  const input = render({ onSubmitReasoning: async () => { count++; return true } })
  type(input, 'line one')
  await act(async () => {
    key(input, { shiftKey: true })
    key(input, { nativeEvent: { isComposing: true } })
    key(input, { nativeEvent: { keyCode: 229 } })
  })
  assert.equal(count, 0)
  assert.equal(input.value, 'line one')
})

test('waiting, empty drafts and repeated key events do not send', async () => {
  let count = 0
  const input = render({ waiting: true, onSubmitReasoning: async () => { count++ } })
  type(input, 'answer')
  await act(async () => key(input))
  render({ waiting: false, onSubmitReasoning: async () => { count++ } })
  await act(async () => key(input, { repeat: true }))
  type(input, '   ')
  await act(async () => key(input))
  assert.equal(count, 0)
})

test('failed sends keep the composer and draft', async () => {
  const input = render({ onSubmitReasoning: async () => false })
  type(input, 'keep my answer')
  await act(async () => key(input))
  assert.equal(document.querySelector('textarea').value, 'keep my answer')
})

test('editing a new draft while sending does not lose it on completion', async () => {
  let finish
  const input = render({ onSubmitReasoning: () => new Promise((resolve) => { finish = resolve }) })
  type(input, 'first answer')
  act(() => key(input))
  type(input, 'next question')
  await act(async () => finish(true))
  assert.equal(input.value, 'next question')
})

test('no session or messages means no reply box yet', () => {
  assert.equal(render({ canReply: false }), null)
  assert.equal(render({ messages: [] }), null)
})
