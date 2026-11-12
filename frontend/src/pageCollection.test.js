import test from 'node:test'
import assert from 'node:assert/strict'
import { collectPageContext } from './pageCollection.js'

const collector = () => ({ ok: true })
const api = (executeScript) => ({ scripting: { executeScript } })

test('returns the main frame context', async () => {
  const result = await collectPageContext(api(async () => [
    { frameId: 2, result: { ok: false } },
    { frameId: 0, result: { ok: true } },
  ]), 1, collector)
  assert.equal(result.ok, true)
})

test('reports a missing Chrome injection result', async () => {
  await assert.rejects(collectPageContext(api(async () => []), 1, collector), /no page data/)
})

test('preserves Chrome permission errors', async () => {
  await assert.rejects(collectPageContext(api(async () => { throw new Error('Cannot access contents') }), 1, collector), /Cannot access/)
})

test('bounds a stalled page reader', async () => {
  await assert.rejects(collectPageContext(api(() => new Promise(() => {})), 1, collector, 5), /timed out/)
})
