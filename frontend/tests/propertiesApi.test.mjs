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
  vm.runInContext(source + '\nthis.api = { publishProperty, exploreProperties, getBuyerFilters, saveBuyerFilters, decideProperty, getMatches, getPendingCandidates, decideCandidate, getProposals, getProposal, sendProposal, respondToProposal };', context)
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

test('reads and saves buyer filters with the authenticated preferences contract', async () => {
  const filters = {
    price_min: '500.00',
    price_max: null,
    surface_min: null,
    surface_max: '90.00',
    bedrooms_min: 2,
    bathrooms_min: null,
    people_min: 1,
    shared_accommodation: false,
  }
  const { api, calls } = harness({
    response: { ok: true, status: 200, data: { filters } },
  })

  const loaded = await api.getBuyerFilters()
  await api.saveBuyerFilters(filters)

  assert.equal(loaded.data.filters, filters)
  assert.equal(calls[0][0], '/api/auth/preferences')
  assert.equal(calls[0][1].cache, 'no-store')
  assert.equal(calls[1][0], '/api/auth/preferences')
  assert.equal(calls[1][1].method, 'PUT')
  assert.equal(calls[1][1].headers['Content-Type'], 'application/json')
  assert.deepEqual(JSON.parse(calls[1][1].body), filters)
})

test('sends decisions to the selected listing endpoint with only the decision', async () => {
  const { api, calls } = harness()

  await api.decideProperty('listing/id', 'LIKE')

  assert.equal(calls[0][0], '/api/inmuebles/listing%2Fid/decision')
  assert.equal(calls[0][1].method, 'POST')
  assert.equal(calls[0][1].headers['Content-Type'], 'application/json')
  assert.deepEqual(JSON.parse(calls[0][1].body), { decision: 'LIKE' })
})

test('loads private match and pending-candidate pages with the shared cursor contract', async () => {
  const { api, calls } = harness()

  await api.getMatches({ limit: 12, cursor: 'match cursor' })
  await api.getPendingCandidates()

  assert.equal(calls[0][0], '/api/matches?limit=12&cursor=match+cursor')
  assert.equal(calls[1][0], '/api/matches/candidatos?limit=20')
  assert.equal(calls[0][1].cache, 'no-store')
  assert.match(calls[0][1].headers.Authorization, /^Bearer firebase-id-token$/)
})

test('sends seller decisions only to the selected candidate', async () => {
  const { api, calls } = harness()

  await api.decideCandidate('candidate/id', 'ACCEPT')

  assert.equal(calls[0][0], '/api/matches/candidaturas/candidate%2Fid/decision')
  assert.equal(calls[0][1].method, 'POST')
  assert.equal(calls[0][1].headers['Content-Type'], 'application/json')
  assert.deepEqual(JSON.parse(calls[0][1].body), { decision: 'ACCEPT' })
})

test('preserves listing availability in existing matches', async () => {
  const items = [
    { id: 'match-closed', listing: { id: 'closed', available: false } },
    { id: 'match-open', listing: { id: 'open', available: true } },
  ]
  const { api } = harness({ response: { ok: true, status: 200, data: { items } } })

  const result = await api.getMatches()

  assert.deepEqual(result.data.items.map(({ listing }) => listing.available), [false, true])
})

test('uses the private proposal paths and keeps the idempotency key supplied by the caller', async () => {
  const { api, calls } = harness()

  await api.getProposals({ cursor: 'proposal cursor' })
  await api.getProposal('proposal/id')
  await api.sendProposal('listing/id', 'buyer-uid', 'existing-intent-key')
  await api.respondToProposal('proposal/id', 'CANCEL')

  assert.deepEqual(calls.map(([path]) => path), [
    '/api/propuestas?limit=20&cursor=proposal+cursor',
    '/api/propuestas/proposal%2Fid',
    '/api/inmuebles/listing%2Fid/propuestas',
    '/api/propuestas/proposal%2Fid/decision',
  ])
  for (const [, request] of calls) assert.equal(request.headers.Authorization, 'Bearer firebase-id-token')
  assert.deepEqual(JSON.parse(calls[2][1].body), { buyer_uid: 'buyer-uid', idempotency_key: 'existing-intent-key' })
  assert.deepEqual(JSON.parse(calls[3][1].body), { decision: 'CANCEL' })
})
