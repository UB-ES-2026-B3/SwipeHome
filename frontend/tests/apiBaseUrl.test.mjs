import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'
import { apiUrl, joinApiUrl } from '../src/api/baseUrl.js'

// Backend en otro origen (Azure Container Apps), con barra final a propósito.
const BASE = 'https://swipehome-api.example.azurecontainerapps.io/'
const ORIGIN = BASE.replace(/\/$/, '')

// Ejecuta el módulo real como en los demás tests, pero con apiUrl ligada a BASE.
function load(file, names) {
  const source = readFileSync(new URL(`../src/api/${file}`, import.meta.url), 'utf8')
    .replace(
      /^import \{[\s\S]*?\} from 'firebase\/auth'$/m,
      'const { sendPasswordResetEmail, signInWithCustomToken, signInWithEmailAndPassword, signOut } = sdk',
    )
    .replace(/^import .* from '..\/firebase'$/m, '')
    .replace(/^import .* from '.\/baseUrl'$/m, '')
    .replace(/^export /gm, '')
  const urls = []
  const user = { getIdToken: async () => 'id-token' }
  const context = vm.createContext({
    auth: { currentUser: user },
    sdk: {
      sendPasswordResetEmail: async () => {},
      signInWithCustomToken: async () => {},
      signInWithEmailAndPassword: async () => ({ user }),
      signOut: async () => {},
    },
    apiUrl: (path) => joinApiUrl(BASE, path),
    FormData,
    URLSearchParams,
    console: { error() {} },
    fetch: async (url) => {
      urls.push(url)
      return { ok: true, status: 200, json: async () => ({}) }
    },
  })
  vm.runInContext(source + `\nthis.api = { ${names.join(', ')} };`, context)
  return { api: context.api, urls }
}

test('joinApiUrl keeps relative paths when the base is empty and never doubles slashes', () => {
  assert.equal(joinApiUrl('', '/api/health'), '/api/health')
  assert.equal(joinApiUrl(undefined, '/api/health'), '/api/health')
  assert.equal(joinApiUrl('https://api.example.com', '/api/health'), 'https://api.example.com/api/health')
  assert.equal(joinApiUrl('https://api.example.com//', '/api/health'), 'https://api.example.com/api/health')
})

test('apiUrl is relative when VITE_API_BASE_URL is not defined (node, local, Render)', () => {
  assert.equal(apiUrl('/api/inmuebles'), '/api/inmuebles')
})

test('with a base URL every backend request goes to <base>/api/... without a double slash', async () => {
  const properties = load('properties.js', [
    'getActiveProperties', 'exploreProperties', 'getConfirmedMatches', 'getPendingCandidates',
    'decideCandidate', 'decideProperty', 'publishProperty',
  ])
  await properties.api.getActiveProperties()
  await properties.api.exploreProperties('c1')
  await properties.api.getConfirmedMatches()
  await properties.api.getPendingCandidates()
  await properties.api.decideCandidate('m 1', 'ACCEPT')
  await properties.api.decideProperty('p1', 'LIKE')
  await properties.api.publishProperty({}, [])

  const notifications = load('notifications.js', ['getNotifications'])
  await notifications.api.getNotifications({ limit: 2 })

  const auth = load('auth.js', ['registerUser', 'fetchCurrentUser', 'logout', 'updateProfile', 'changePassword'])
  await auth.api.registerUser({ email: 'a@example.com', password: 'x' })
  await auth.api.fetchCurrentUser()
  await auth.api.updateProfile({ name: 'Ana' })
  await auth.api.changePassword('old', 'new')
  await auth.api.logout()

  const urls = [...properties.urls, ...notifications.urls, ...auth.urls]
  assert.deepEqual(urls, [
    `${ORIGIN}/api/inmuebles`,
    `${ORIGIN}/api/inmuebles/explorar?limit=20&cursor=c1`,
    `${ORIGIN}/api/matches?limit=20`,
    `${ORIGIN}/api/candidatos?limit=20`,
    `${ORIGIN}/api/matches/m%201/decision-vendedor`,
    `${ORIGIN}/api/inmuebles/p1/decision`,
    `${ORIGIN}/api/inmuebles`,
    `${ORIGIN}/api/notificaciones?limit=2`,
    `${ORIGIN}/api/auth/register`,
    `${ORIGIN}/api/auth/me`,
    `${ORIGIN}/api/auth/me`,
    `${ORIGIN}/api/auth/me/password`,
    `${ORIGIN}/api/auth/logout`,
  ])
  for (const url of urls) assert.equal(url.includes('//api'), false, url)
})
