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
    fetch: async (path, options) => {
      calls.push([path, options])
      if (networkFailure) throw new Error('offline')
      return { ok: response.ok, status: response.status, json: async () => response.data }
    },
  })
  vm.runInContext(source + '\nthis.api = { publishProperty };', context)
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
