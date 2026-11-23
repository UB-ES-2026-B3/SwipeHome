import assert from 'node:assert/strict'
import { File } from 'node:buffer'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/api/properties.js', import.meta.url), 'utf8')
  .replace(/^import .* from '..\/firebase'$/m, '')
  .replace(/^export /gm, '')

function harness({ user, response = { ok: true, status: 201, data: { id: 'listing-1' } }, networkFailure = false } = {}) {
  const calls = []
  const auth = { currentUser: user ?? { getIdToken: async () => 'firebase-id-token' } }
  const context = vm.createContext({
    auth,
    FormData,
    URLSearchParams,
    fetch: async (path, options) => {
      calls.push([path, options])
      if (networkFailure) throw new Error('offline')
      return { ok: response.ok, status: response.status, json: async () => response.data }
    },
  })
  vm.runInContext(source + '\nthis.api = { publishProperty, exploreProperties, decideProperty, getConfirmedMatches, getPendingCandidates, decideCandidate, getProposals, getProposal, createProposal, resolveProposal, getSearchPreferences, saveSearchPreferences, resetSearchPreferences, getFilterOptions };', context)
  return { api: context.api, calls, auth }
}

test('sends multipart data, ordered photos and Firebase ID token without setting Content-Type', async () => {
  const { api, calls } = harness()
  const photos = [
    new File(['first'], 'first.jpg', { type: 'image/jpeg' }),
    new File(['second'], 'second.png', { type: 'image/png' }),
  ]
  const values = { title: 'Piso', shared_accommodation: 'No' }
  const result = await api.publishProperty(values, photos)

  assert.equal(result.ok, true)
  assert.deepEqual(calls.map(([path]) => path), ['/api/inmuebles'])
  const [, options] = calls[0]
  assert.equal(options.method, 'POST')
  assert.equal(options.headers.Authorization, 'Bearer firebase-id-token')
  assert.equal('Content-Type' in options.headers, false)
  assert.equal(options.body.get('title'), 'Piso')
  assert.deepEqual(options.body.getAll('photos').map(({ name }) => name), ['first.jpg', 'second.png'])
})

test('returns API rejection without changing the caller data', async () => {
  const { api } = harness({ response: { ok: false, status: 400, data: { errors: { photos: 'required' } } } })
  const values = { title: 'Keep this title' }
  const result = await api.publishProperty(values, [])

  assert.equal(result.ok, false)
  assert.equal(result.status, 400)
  assert.equal(values.title, 'Keep this title')
})

test('returns an authentication rejection and preserves network errors', async () => {
  const anonymous = harness({ user: null })
  anonymous.auth.currentUser = null
  const unauthenticated = await anonymous.api.publishProperty({}, [])
  assert.equal(unauthenticated.ok, false)
  assert.equal(unauthenticated.status, 401)

  const offline = harness({ networkFailure: true })
  await assert.rejects(offline.api.publishProperty({}, []), /offline/)
  await assert.rejects(offline.api.decideProperty('listing-1', 'LIKE'), /offline/)
})

test('maps the dashboard form aliases to the backend contract', async () => {
  const { api, calls } = harness()
  await api.publishProperty({
    title: 'Piso',
    address: 'Calle 1',
    locality: 'Barcelona',
    postalCode: '08001',
    description: 'Luminoso',
    price: '950',
    area: '65',
    bedrooms: '2',
    bathrooms: '1',
    tenants: '3',
    shared: 'yes',
  }, [{ file: new File(['photo'], 'photo.webp', { type: 'image/webp' }) }])

  const [, options] = calls[0]
  assert.equal(options.body.get('street'), 'Calle 1')
  assert.equal(options.body.get('city'), 'Barcelona')
  assert.equal(options.body.get('postal_code'), '08001')
  assert.equal(options.body.get('surface'), '65')
  assert.equal(options.body.get('people'), '3')
  assert.equal(options.body.get('shared_accommodation'), 'Sí')
  assert.equal(options.body.get('photos').name, 'photo.webp')
})

test('explores with the cursor-based US4 API contract', async () => {
  const { api, calls } = harness()

  await api.exploreProperties('opaque cursor/with spaces')
  await api.exploreProperties()

  assert.equal(calls[0][0], '/api/inmuebles/explorar?limit=20&cursor=opaque+cursor%2Fwith+spaces')
  assert.equal(calls[1][0], '/api/inmuebles/explorar?limit=20')
  assert.match(calls[0][1].headers.Authorization, /^Bearer /)
})

test('reads confirmed matches with authentication and an opaque pagination cursor', async () => {
  const { api, calls } = harness()
  const { signal } = new AbortController()

  await api.getConfirmedMatches(null, signal)
  await api.getConfirmedMatches('opaque cursor/with spaces')

  assert.deepEqual(calls.map(([path]) => path), [
    '/api/matches?limit=20',
    '/api/matches?limit=20&cursor=opaque+cursor%2Fwith+spaces',
  ])
  assert.equal(calls[0][1].method, 'GET')
  assert.equal(calls[0][1].headers.Authorization, 'Bearer firebase-id-token')
  assert.equal(calls[0][1].signal, signal)
})

test('filters both seller lists and sends decisions for a specific candidacy', async () => {
  const { api, calls } = harness()
  await api.getPendingCandidates('page two', undefined, 'home/one')
  await api.getConfirmedMatches(null, undefined, 'home/one')
  await api.decideCandidate('match/one', 'LIKE')
  await api.decideCandidate('match/two', 'PASS')
  assert.deepEqual(calls.map(([path]) => path), [
    '/api/candidatos?limit=20&cursor=page+two&inmueble=home%2Fone',
    '/api/matches?limit=20&inmueble=home%2Fone',
    '/api/matches/match%2Fone/decision-vendedor',
    '/api/matches/match%2Ftwo/decision-vendedor',
  ])
  assert.deepEqual(calls.map(([, options]) => options.method), ['GET', 'GET', 'POST', 'POST'])
  for (const [, options] of calls) assert.equal(options.headers.Authorization, 'Bearer firebase-id-token')
  assert.equal(calls[2][1].headers['Content-Type'], 'application/json')
  assert.deepEqual(JSON.parse(calls[2][1].body), { decision: 'LIKE' })
  assert.deepEqual(JSON.parse(calls[3][1].body), { decision: 'PASS' })
})

test('preserves decision response statuses and network errors for seller actions', async () => {
  for (const status of [401, 409, 500]) {
    const { api } = harness({ response: { ok: false, status, data: { error: 'failed' } } })
    const result = await api.decideCandidate('candidate', 'LIKE')
    assert.equal(result.ok, false)
    assert.equal(result.status, status)
  }
  const { api } = harness({ networkFailure: true })
  await assert.rejects(api.decideCandidate('candidate', 'LIKE'), /offline/)
  await assert.rejects(api.getPendingCandidates(), /offline/)
  await assert.rejects(api.getConfirmedMatches(), /offline/)
})

test('queries and creates proposals using the authenticated US9 API', async () => {
  const { api, calls } = harness()
  await api.getProposals('opaque cursor')
  await api.getProposal('proposal/one')
  await api.createProposal('home-1', 'match-1', 'request-1')
  await api.resolveProposal('proposal/one', 'cancelar')
  assert.deepEqual(calls.map(([path]) => path), [
    '/api/propuestas?limit=20&cursor=opaque+cursor',
    '/api/propuestas/proposal%2Fone',
    '/api/propuestas',
    '/api/propuestas/proposal%2Fone/cancelar',
  ])
  assert.deepEqual(calls.map(([, options]) => options.method), ['GET', 'GET', 'POST', 'POST'])
  for (const [, options] of calls) assert.equal(options.headers.Authorization, 'Bearer firebase-id-token')
  assert.deepEqual(JSON.parse(calls[2][1].body), { listing_id: 'home-1', match_id: 'match-1', request_id: 'request-1' })
  assert.deepEqual(JSON.parse(calls[3][1].body), {})
})

test('sends decisions to the selected listing endpoint with only the decision', async () => {
  const { api, calls } = harness()

  await api.decideProperty('listing/id', 'LIKE')

  assert.equal(calls[0][0], '/api/inmuebles/listing%2Fid/decision')
  assert.equal(calls[0][1].method, 'POST')
  assert.equal(calls[0][1].headers['Content-Type'], 'application/json')
  assert.deepEqual(JSON.parse(calls[0][1].body), { decision: 'LIKE' })
})

test('uses the buyer search preference and filter-option endpoints', async () => {
  const { api, calls } = harness()

  await api.getSearchPreferences()
  await api.getFilterOptions()
  await api.saveSearchPreferences({ bedrooms: 0, is_shared: false })
  await api.resetSearchPreferences()

  assert.deepEqual(calls.map(([path]) => path), [
    '/api/exploracion/filtros',
    '/api/inmuebles/opciones-filtro',
    '/api/exploracion/filtros',
    '/api/exploracion/filtros',
  ])
  assert.deepEqual(calls.map(([, options]) => options.method), ['GET', 'GET', 'PUT', 'DELETE'])
  assert.deepEqual(JSON.parse(calls[2][1].body), { bedrooms: 0, is_shared: false })
})
