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
  people: 3, shared_accommodation: false, available: true, photos: [], created_at: stamp,
}
const candidate = (id, name) => ({ id, buyer: { id, name }, listing: home, created_at: stamp })
const proposal = (status) => ({ id: 'proposal', status, listing: home, seller: { name: 'Vendedora' } })
const defaults = Object.fromEntries([
  'price_min', 'price_max', 'surface_min', 'surface_max', 'bedrooms_min', 'bathrooms_min',
  'people_min', 'shared_accommodation',
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
      success({ decision: { listing_id: 'home', value: 'LIKE', seller_decision: 'PENDING' }, match: null }),
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
  await tab.text('Interés enviado al vendedor.')
  assert.equal(await tab.evaluate(() => document.body.innerText.includes('¡Match confirmado!')), false)
})

component('US 5.9 candidaturas paginadas y conflicto con actualización fallida', 'SellerCandidates', {
  role: 'SELLER',
  replies: {
    getPendingCandidates: [
      success(page([candidate('first', 'Ana')], 'next'), 'load'),
      success(page([candidate('second', 'Bea')])),
      error(503, 'No se pudo actualizar la lista.'),
      success(page([])),
    ],
    decideCandidate: [error(409, 'Candidatura resuelta.')],
  },
}, async (tab) => {
  await tab.text('Cargando candidaturas…')
  await release(tab, 'load')
  await tab.text('Ana')
  await tab.click('Cargar más candidaturas')
  await tab.text('Bea')
  await tab.text('Ana')
  assert.deepEqual(await calls(tab, 'getPendingCandidates'), [[{}], [{ cursor: 'next' }]])
  await tab.click('Rechazar', '.seller-dashboard__candidate:nth-child(2)')
  await tab.text('No se pudo actualizar la lista.')
  assert.equal(await tab.evaluate(() => document.body.innerText.includes('Se actualizó la lista.')), false)
  await tab.click('Reintentar')
  await tab.text('No tienes candidaturas pendientes.')
  assert.deepEqual(await calls(tab, 'decideCandidate'), [['second', 'REJECT']])
})

component('US 5.9 matches privados de comprador con paginación y disponibilidad', 'MatchesPage', {
  replies: { getMatches: [
    success(page([candidate('first', 'Ana')], 'cursor')),
    success(page([{ ...candidate('second', 'Bea'), listing: { ...home, title: 'Piso cerrado', available: false } }])),
  ] },
}, async (tab) => {
  await tab.text(home.title)
  assert.equal(await hasButton(tab, 'Enviar propuesta'), false)
  await tab.keyboardClick('Cargar más matches')
  await tab.text('Piso cerrado')
  await tab.text('Vivienda no disponible')
  await tab.text(home.title)
  assert.deepEqual(await calls(tab, 'getMatches'), [[{}], [{ cursor: 'cursor' }]])
})

component('US 8.6 validación accesible y restablecimiento fallido conservan los filtros', 'PreferenceFilters', {
  refreshFailure: true,
  replies: {
    getBuyerFilters: [success({ filters: { ...defaults, price_max: '650.00' } })],
    saveBuyerFilters: [
      error(503, 'Error temporal al restablecer.'),
      success({ filters: { ...defaults, price_max: '700.00' } }, 'save'),
    ],
  },
}, async (tab) => {
  await tab.fill('#filter-price_min', '800')
  await tab.click('Aplicar filtros')
  await tab.text('El mínimo no puede superar el máximo.')
  assert.equal(await tab.evaluate(() => document.querySelector('#filter-price_min').getAttribute('aria-describedby')),
    'filter-price_min-error')
  assert.equal((await calls(tab, 'saveBuyerFilters')).length, 0)
  await tab.click('Cancelar cambios')
  await tab.click('Restablecer filtros')
  await tab.text('Error temporal al restablecer.')
  assert.equal(await tab.evaluate(() => Number(document.querySelector('#filter-price_max').value)), 650)
  await tab.fill('#filter-price_max', '700')
  await tab.evaluate(() => {
    document.querySelector('form').requestSubmit()
    document.querySelector('form').requestSubmit()
  })
  await tab.text('Aplicando…')
  assert.equal(await disabled(tab, '#filter-price_max'), true)
  assert.deepEqual(await calls(tab, 'saveBuyerFilters'), [[defaults], [{ ...defaults, price_max: '700' }]])
  await release(tab, 'save')
  await tab.text('Filtros guardados, pero no se pudieron cargar las viviendas.')
})

component('US 8.6 integración de filtros con el explorador durante guardado y refresco', 'BuyerHome', {
  replies: {
    exploreProperties: [
      success(page([home])),
      success(page([{ ...home, id: 'filtered', title: 'Piso filtrado' }]), 'refresh'),
    ],
    getBuyerFilters: [success({ filters: defaults })],
    saveBuyerFilters: [success({ filters: { ...defaults, price_max: '600.00' } }, 'save')],
  },
}, async (tab) => {
  await tab.text(home.title)
  await tab.click('Filtros')
  await tab.fill('#filter-price_max', '600')
  await tab.click('Aplicar filtros')
  await tab.text('Aplicando…')
  assert.equal(await disabled(tab, 'button[aria-label="Me interesa"]'), true)
  await release(tab, 'save')
  await tab.text('Cargando viviendas…')
  await release(tab, 'refresh')
  await tab.text('Piso filtrado')
  await tab.text('Filtros guardados y aplicados.')
  assert.deepEqual(await calls(tab, 'decideProperty'), [])
  assert.equal(await disabled(tab, 'button[aria-label="Me interesa"]'), false)
})

component('US 9.7 conflicto de exclusividad bloquea todos los matches de la vivienda', 'MatchesPage', {
  role: 'SELLER',
  replies: {
    getMatches: [
      success(page([candidate('first', 'Ana'), candidate('second', 'Bea')])),
      success(page([candidate('first', 'Ana'), candidate('second', 'Bea')].map((row) => ({ ...row, proposal_pending: true })))),
    ],
    sendProposal: [{ ...error(409, 'Ya existe una propuesta pendiente.'), hold: 'send' }],
  },
}, async (tab) => {
  await tab.text('Comprador/a: Ana')
  await tab.click('Enviar propuesta', '.matches-page__item:nth-child(1)')
  await tab.text('Enviando propuesta…')
  assert.equal(await disabled(tab, '.matches-page__item:nth-child(2) button'), true)
  const [[listingId, buyerId, key]] = await calls(tab, 'sendProposal')
  assert.equal(listingId, 'home')
  assert.equal(buyerId, 'first')
  assert.match(key, /^[0-9a-f-]{36}$/)
  await release(tab, 'send')
  await tab.text('Ya existe una propuesta pendiente.')
  await tab.text('Hay una propuesta pendiente para esta vivienda.')
  assert.equal(await hasButton(tab, 'Enviar propuesta'), false)
})

component('US 9.8 una propuesta obsoleta queda sin acciones hasta recuperar el estado', 'ProposalsPage', {
  path: '/propuestas/proposal',
  replies: {
    getProposal: [success(proposal('PENDING')), error(503, 'Fallo al consultar el estado.'), success(proposal('CANCELLED'))],
    respondToProposal: [{ ...error(409, 'Propuesta resuelta.'), hold: 'decision' }],
  },
}, async (tab) => {
  await tab.text('Estado: Pendiente')
  assert.equal(await hasButton(tab, 'Cancelar propuesta'), false)
  await tab.keyboardClick('Aceptar propuesta')
  await tab.text('Guardando respuesta…')
  assert.equal(await tab.evaluate(() => [...document.querySelectorAll('.proposal-actions button')].every((button) => button.disabled)), true)
  await release(tab, 'decision')
  await tab.text('Fallo al consultar el estado.')
  assert.equal(await hasButton(tab, 'Aceptar propuesta'), false)
  await tab.click('Reintentar')
  await tab.text('Estado: Cancelada')
  assert.equal(await hasButton(tab, 'Rechazar propuesta'), false)
  assert.deepEqual(await calls(tab, 'respondToProposal'), [['proposal', 'ACCEPT']])
})
