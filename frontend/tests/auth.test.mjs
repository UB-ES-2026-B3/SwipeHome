import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

// Ejecuta el módulo real con sus dos imports sustituidos por dobles.
// Sin dependencias nuevas; fetch y Firebase nunca acceden a la red.
const source = readFileSync(new URL('../src/api/auth.js', import.meta.url), 'utf8')
  .replace(/^import .* from 'firebase\/auth'$/m, 'const { signInWithCustomToken, signInWithEmailAndPassword, signOut } = sdk')
  .replace(/^import .* from '..\/firebase'$/m, '')
  .replace(/^export /gm, '')

function harness({ status = 200, data = {}, exchangeFailure = false, networkFailure = false } = {}) {
  const calls = []
  const user = { getIdToken: async () => 'id-token' }
  const auth = { currentUser: user }
  const sdk = {
    signInWithCustomToken: async (_auth, token) => {
      calls.push(['exchange', token])
      if (exchangeFailure) throw new Error('unavailable')
    },
    signInWithEmailAndPassword: async () => ({ user }),
    signOut: async () => { calls.push(['signOut']); auth.currentUser = null },
  }
  const context = vm.createContext({
    sdk, auth,
    fetch: async (path, options) => {
      calls.push(['fetch', path, options])
      if (networkFailure) throw new Error('offline')
      return { ok: status < 400, status, json: async () => ({ ...data }) }
    },
  })
  vm.runInContext(source + '\nthis.api = { logout, changePassword, updateProfile };', context)
  return { api: context.api, auth, user, calls }
}

test('logout revokes on server before clearing Firebase SDK', async () => {
  const { api, auth, calls } = harness({ status: 204 })
  await api.logout()
  assert.equal(calls[0][1], '/api/auth/logout')
  assert.equal(calls[0][2].method, 'POST')
  assert.equal(calls[0][2].headers.Authorization, 'Bearer id-token')
  assert.equal(calls[1][0], 'signOut')
  assert.equal(auth.currentUser, null)
})

for (const failure of [{ status: 500 }, { networkFailure: true }]) {
  test('logout failure preserves SDK session: ' + JSON.stringify(failure), async () => {
    const { api, auth, calls } = harness(failure)
    await assert.rejects(api.logout())
    assert.notEqual(auth.currentUser, null)
    assert.equal(calls.some(([name]) => name === 'signOut'), false)
  })
}

test('logout without Firebase user is locally idempotent', async () => {
  const { api, auth, calls } = harness()
  auth.currentUser = null
  await api.logout()
  assert.equal(calls.length, 1)
  assert.equal(calls[0][0], 'signOut')
})

test('expired SDK session is cleared without sending a stale token', async () => {
  const { api, user, calls } = harness()
  user.getIdToken = async () => { throw { code: 'auth/user-token-expired' } }
  await api.logout()
  assert.equal(calls.length, 1)
  assert.equal(calls[0][0], 'signOut')
})

test('password success exchanges continuity credential and never exposes it to callers', async () => {
  const { api, calls } = harness({ data: { custom_token: 'sensitive-continuity' } })
  const result = await api.changePassword(' old ', ' new password 🙂 ')
  assert.equal(result.ok, true)
  assert.equal(calls[0][1], '/api/auth/me/password')
  assert.deepEqual(JSON.parse(calls[0][2].body), { current_password: ' old ', new_password: ' new password 🙂 ' })
  assert.equal(calls[1][0], 'exchange')
  assert.equal(calls[1][1], 'sensitive-continuity')
  assert.equal('custom_token' in result.data, false)
})

test('failed continuity exchange reports persisted change and need to reauthenticate', async () => {
  const { api } = harness({ data: { custom_token: 'sensitive-continuity' }, exchangeFailure: true })
  const result = await api.changePassword('old', 'new password value')
  assert.equal(result.ok, true)
  assert.equal(result.data.reauthentication_required, true)
  assert.equal('custom_token' in result.data, false)
})

test('validation rejection never exchanges a credential', async () => {
  const { api, calls } = harness({ status: 400, data: { error: 'invalid' } })
  const result = await api.updateProfile({ role: 'ADMIN' })
  assert.equal(result.ok, false)
  assert.equal(calls.length, 1)
})
