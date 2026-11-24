import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import react from '@vitejs/plugin-react'
import { createServer } from 'vite'
import { startChromium, waitFor } from '../e2e/chromium.mjs'

const mocks = new Map([
  ['../api/properties', fileURLToPath(new URL('./api.mock.mjs', import.meta.url))],
  ['../hooks/useAuth', fileURLToPath(new URL('./auth.mock.mjs', import.meta.url))],
])
let browser, server, origin
const success = (data, hold) => ({ status: 200, data, hold })
const error = (status, text) => ({ status, data: { error: text } })
const page = (items, cursor = null) => ({ items, next_cursor: cursor })
const stamp = '2026-11-08T00:00:00Z'
const home = {
  id: 'home', title: 'Piso de prueba', street: 'Calle Mayor 1', city: 'Barcelona', postal_code: '08001',
  description: 'Descripción del inmueble', price: '950.50', surface: '65.50', bedrooms: 2, bathrooms: 1,
  people: 3, shared_accommodation: false, availability: 'ACTIVE', photos: [], created_at: stamp,
}
const candidate = (id, name) => ({ id, status: 'CONFIRMED', buyer: { id, name }, seller: { id: 'seller', name: 'Vendedora' }, listing: home, confirmed_at: stamp, created_at: stamp })
const proposal = (status) => ({ id: 'proposal', created_at: stamp, status, listing: home, seller: { name: 'Vendedora' } })
const defaults = Object.fromEntries([
  'min_price', 'max_price', 'min_area', 'max_area', 'bedrooms', 'min_bathrooms',
  'people_offered', 'is_shared', 'city', 'postal_code',
].map((field) => [field, null]))

before(async () => {
  server = await createServer({
    configFile: false, envFile: false, logLevel: 'error',
    cacheDir: process.env.SWIPEHOME_QA_VITE_CACHE && join(process.env.SWIPEHOME_QA_VITE_CACHE, 'components'),
    server: { host: '127.0.0.1', port: 0, hmr: false },
    plugins: [react(), {
      name: 'swipehome-component-dependencies',
      enforce: 'pre',
      resolveId(source) { return mocks.get(source) },
    }],
  })
  await server.listen()
  origin = `http://127.0.0.1:${server.httpServer.address().port}`
  browser = await startChromium(process.env.SWIPEHOME_E2E_CHROME)
})

after(async () => {
  try { await browser?.close() } finally { await server?.close() }
})

function component(name, view, options, assertions) {
  test(name, { timeout: 45000 }, async () => {
    const tab = await browser.tab()
    try {
      await tab.navigate(origin + '/component/index.html')
      await waitFor(() => tab.evaluate(() => Boolean(window.qa)), 'React listo para montar')
      await tab.evaluate((componentName, settings) => window.qa.mount(componentName, settings), view, options)
      await assertions(tab)
      assert.deepEqual(await tab.evaluate(() => window.qa.unexpected), [])
      if (process.env.SWIPEHOME_QA_DEBUG === '1') await browser.capture(name)
    } catch (failure) {
      await browser.capture(name + '-failed')
      throw failure
    }
  })
}

const calls = (tab, name) => tab.evaluate((method) =>
  window.qa.calls.filter((record) => record.name === method).map((record) => record.args), name)
const release = (tab, key) => tab.evaluate((name) => window.qa.release(name), key)
const disabled = (tab, selector) => tab.evaluate((query) => document.querySelector(query).disabled, selector)
const hasButton = (tab, title) => tab.evaluate((label) =>
  [...document.querySelectorAll('button')].some((button) => button.innerText.trim() === label), title)

component('US 5.8 interés pendiente y confirmación incoherente reintentable', 'BuyerHome', {
  replies: {
    exploreProperties: [success(page([home]))],
    decideProperty: [
      success({ decision: { listing_id: 'ajena', value: 'LIKE', seller_decision: 'PENDING' }, match: null }, 'interest'),
      success({ decision: { listing_id: 'home', value: 'LIKE' }, match: { id: 'pending', listing_id: 'home', status: 'PENDING' } }),
    ],
  },
}, async (tab) => {
  await tab.text(home.title)
  await tab.evaluate(() => {
    const control = document.querySelector('button[aria-label="Me interesa"]')
    control.click()
    control.click()
  })
  assert.deepEqual(await calls(tab, 'decideProperty'), [['home', 'LIKE']])
  assert.equal(await disabled(tab, 'button[aria-label="Me interesa"]'), true)
  await release(tab, 'interest')
  await tab.text('El servidor no confirmó la decisión.')
  await tab.text(home.title)
  await tab.keyboardClick('Reintentar')
  await tab.text('Interés enviado')
  assert.equal(await tab.evaluate(() => document.body.innerText.includes('¡Match confirmado!')), false)
})

component('US 5.9 candidaturas paginadas y conflicto con actualización fallida', 'SellerMatchesPage', {
  role: 'SELLER',
  replies: {
    getActiveProperties: Array.from({ length: 2 }, () => success({ properties: [home] })),
    getConfirmedMatches: Array.from({ length: 4 }, () => success(page([]))),
    getProposals: Array.from({ length: 2 }, () => success(page([]))),
    getPendingCandidates: [
      success(page([{ ...candidate('first', 'Ana'), status: 'PENDING' }], 'next'), 'load'),
      success(page([{ ...candidate('second', 'Bea'), status: 'PENDING' }])),
      error(503, 'No se pudo actualizar la lista.'),
      success(page([])),
    ],
    decideCandidate: [error(409, 'Candidatura resuelta.')],
  },
}, async (tab) => {
  await tab.text('Cargando pendientes…')
  await release(tab, 'load')
  await tab.text('Ana')
  await tab.click('Cargar más')
  await tab.text('Bea')
  await tab.text('Ana')
  assert.deepEqual(await calls(tab, 'getPendingCandidates'), [[null, {}, 'home'], ['next', {}, 'home']])
  await tab.click('No me interesa: Bea, Piso de prueba')
  await tab.text('No se pudo actualizar la lista.')
  const claimedRefresh = await tab.evaluate(() => document.body.innerText.includes('Hemos actualizado las listas.'))
  await tab.click('Reintentar', '#seller-panel-pending')
  await tab.text('No tienes candidaturas pendientes.')
  assert.deepEqual(await calls(tab, 'decideCandidate'), [['second', 'PASS']])
  assert.equal(claimedRefresh, false, 'No se debe anunciar una actualización que respondió 503')
})

component('US 5.9 matches privados de comprador con paginación y disponibilidad', 'BuyerMatchesPage', {
  replies: { getConfirmedMatches: [
    success(page([candidate('first', 'Ana')], 'cursor')),
    success(page([{ ...candidate('second', 'Bea'), listing: { ...home, title: 'Piso cerrado', availability: 'CLOSED' } }])),
  ] },
}, async (tab) => {
  await tab.text(home.title)
  assert.equal(await hasButton(tab, 'Proponer selección'), false)
  await tab.keyboardClick('Cargar más')
  await tab.text('Piso cerrado')
  await tab.text('Anuncio cerrado')
  await tab.text(home.title)
  assert.deepEqual(await calls(tab, 'getConfirmedMatches'), [[null, {}], ['cursor', {}]])
})

component('US 8.6 validación accesible y restablecimiento fallido conservan los filtros', 'SearchPreferencesForm', {
  replies: {
    getSearchPreferences: [success({ ...defaults, max_price: '650.00' })],
    getFilterOptions: [success({ cities: [] })],
    resetSearchPreferences: [error(503, 'Error temporal al restablecer.')],
    saveSearchPreferences: [
      success({ ...defaults, max_price: '700.00' }, 'save'),
      success({ ...defaults, max_price: '700.00' }, 'duplicate'),
    ],
  },
}, async (tab) => {
  await tab.fill('#pref-min-price', '800')
  await tab.click('Aplicar filtros')
  await tab.text('Debe ser mayor o igual al precio mínimo.')
  const describedBy = await tab.evaluate(() => document.querySelector('#pref-max-price').getAttribute('aria-describedby'))
  assert.equal(await tab.evaluate(() => document.getElementById('pref-max-price-error').getAttribute('role')), 'alert')
  assert.equal((await calls(tab, 'saveSearchPreferences')).length, 0)
  await tab.click('Cancelar')
  await tab.click('Restablecer filtros')
  await tab.text('Error temporal al restablecer.')
  assert.equal(await tab.evaluate(() => Number(document.querySelector('#pref-max-price').value)), 650)
  await tab.fill('#pref-max-price', '700')
  await tab.evaluate(() => {
    document.querySelector('form').requestSubmit()
    document.querySelector('form').requestSubmit()
  })
  await tab.text('Aplicar filtros')
  assert.equal(await disabled(tab, 'button[type=submit]'), true)
  const requests = await calls(tab, 'saveSearchPreferences')
  await release(tab, 'save')
  if (requests.length > 1) await release(tab, 'duplicate')
  await tab.text('Preferencias aplicadas.')
  assert.deepEqual({ describedBy, requests }, {
    describedBy: 'pref-max-price-error',
    requests: [[{ ...defaults, max_price: '700' }]],
  })
})

component('US 8.6 integración de filtros con el explorador durante guardado y refresco', 'BuyerHome', {
  replies: {
    exploreProperties: [
      success(page([home])),
      success(page([{ ...home, id: 'filtered', title: 'Piso filtrado' }]), 'refresh'),
    ],
    getSearchPreferences: [success(defaults)],
    getFilterOptions: [success({ cities: [] })],
    saveSearchPreferences: [success({ ...defaults, max_price: '600.00' }, 'save')],
  },
}, async (tab) => {
  await tab.text(home.title)
  await tab.click('Filtros')
  await tab.fill('#pref-max-price', '600')
  await tab.click('Aplicar filtros')
  await tab.text('Aplicar filtros')
  assert.equal(await disabled(tab, 'button[type=submit]'), true)
  await release(tab, 'save')
  await tab.text('Cargando viviendas…')
  await release(tab, 'refresh')
  await tab.text('Piso filtrado')
  assert.deepEqual(await calls(tab, 'decideProperty'), [])
  assert.equal(await disabled(tab, 'button[aria-label="Me interesa"]'), false)
})

component('US 9.7 conflicto de exclusividad bloquea todos los matches de la vivienda', 'SellerMatchesPage', {
  role: 'SELLER',
  replies: {
    getActiveProperties: [success({ properties: [home] }), success({ properties: [home] })],
    getPendingCandidates: [success(page([])), success(page([]))],
    getConfirmedMatches: Array.from({ length: 4 }, () => success(page([candidate('first', 'Ana'), candidate('second', 'Bea')]))),
    getProposals: [success(page([])), success(page([{ ...proposal('PENDING'), listing_id: 'home', match_id: 'first' }]))],
    createProposal: [{ ...error(409, 'Ya existe una propuesta pendiente.'), hold: 'send' }],
  },
}, async (tab) => {
  await tab.click('Matches confirmados')
  await tab.click('Proponer selección: Ana, Piso de prueba')
  await tab.text('Enviando propuesta…')
  assert.equal(await disabled(tab, '#seller-panel-confirmed li:nth-child(2) button'), true)
  const [[listingId, buyerId, key]] = await calls(tab, 'createProposal')
  assert.equal(listingId, 'home')
  assert.equal(buyerId, 'first')
  assert.match(key, /^[0-9a-f-]{36}$/)
  await release(tab, 'send')
  await tab.text('La situación de la vivienda ha cambiado.')
  await tab.text('Pendiente')
  assert.equal(await hasButton(tab, 'Proponer selección'), false)
})

component('US 9.8 una propuesta obsoleta queda sin acciones hasta recuperar el estado', 'BuyerProposalsPage', {
  path: '/propuestas/proposal',
  replies: {
    getProposals: [success(page([{ id: 'proposal' }]))],
    getProposal: [success(proposal('PENDING')), error(503, 'Fallo al consultar el estado.'), success(proposal('CANCELLED'))],
    resolveProposal: [{ ...error(409, 'Propuesta resuelta.'), hold: 'decision' }],
  },
}, async (tab) => {
  await tab.text('Pendiente')
  assert.equal(await hasButton(tab, 'Cancelar propuesta'), false)
  await tab.keyboardClick('Aceptar')
  assert.equal(await tab.evaluate(() => [...document.querySelectorAll('.seller-matches__actions button.btn--dark')].every((button) => button.disabled)), true)
  await release(tab, 'decision')
  await tab.text('No se pudo cargar esta propuesta.')
  assert.equal(await tab.evaluate(() => [...document.querySelectorAll('.seller-matches__actions button')].find(button => button.textContent === 'Aceptar').disabled), true)
  await tab.click('Reintentar')
  await tab.text('Cancelada')
  assert.equal(await hasButton(tab, 'Rechazar'), false)
  assert.deepEqual(await calls(tab, 'resolveProposal'), [['proposal', 'aceptar']])
})
