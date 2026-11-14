import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/api/notifications.js', import.meta.url), 'utf8')
  .replace(/^import .* from '..\/firebase'$/m, '')
  .replace(/^export /gm, '')

function harness({ user, response = { ok: true, status: 200, data: { items: [], next_cursor: null } }, networkFailure = false } = {}) {
  const calls = []
  const auth = { currentUser: user ?? { getIdToken: async () => 'firebase-id-token' } }
  const context = vm.createContext({
    auth,
    URLSearchParams,
    console: { error() {} },
    fetch: async (path, options) => {
      calls.push([path, options])
      if (networkFailure) throw new Error('offline')
      return { ok: response.ok, status: response.status, json: async () => response.data }
    },
  })
  vm.runInContext(source + '\nthis.api = { getNotifications };', context)
  return { api: context.api, auth, calls }
}

test('queries the private API with the authenticated token, cursor and no-store cache', async () => {
  const { api, calls } = harness()
  const result = await api.getNotifications({ limit: 2, cursor: 'signed cursor' })

  assert.equal(result.ok, true)
  assert.deepEqual(result.data, { items: [], next_cursor: null })
  assert.equal(calls[0][0], '/api/notificaciones?limit=2&cursor=signed+cursor')
  assert.equal(calls[0][1].method, 'GET')
  assert.equal(calls[0][1].headers.Authorization, 'Bearer firebase-id-token')
  assert.equal(calls[0][1].cache, 'no-store')
})

test('does not call the API without an authenticated Firebase user', async () => {
  const { api, auth, calls } = harness()
  auth.currentUser = null

  const result = await api.getNotifications()

  assert.equal(result.ok, false)
  assert.equal(result.status, 401)
  assert.equal(calls.length, 0)
})

test('returns API failures and distinguishes an unavailable network', async () => {
  const failure = harness({ response: { ok: false, status: 500, data: { error: 'Reintenta.' } } })
  const response = await failure.api.getNotifications()
  assert.equal(response.status, 500)
  assert.equal(response.data.error, 'Reintenta.')

  const offline = harness({ networkFailure: true })
  const network = await offline.api.getNotifications()
  assert.equal(network.status, 0)
  assert.match(network.data.error, /conexión/)
})
