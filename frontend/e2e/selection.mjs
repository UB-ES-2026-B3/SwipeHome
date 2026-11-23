import assert from 'node:assert/strict'
import { text as readStream } from 'node:stream/consumers'
import { setTimeout as delay } from 'node:timers/promises'
import { assertNoOverflow, startApp } from './browser-app.mjs'
import { waitFor } from './chromium.mjs'

const input = JSON.parse(await readStream(process.stdin))
const { scenario, backend } = input

const homeTitle = 'Piso luminoso'
const sendPath = '/api/inmuebles/home/propuestas'
const mutations = []
let nextFault

function holdNext(path, failureStatus = null) {
  const started = Promise.withResolvers()
  const finished = Promise.withResolvers()
  const release = Promise.withResolvers()
  nextFault = { path, failureStatus, started, finished, release: release.promise }
  return { started: started.promise, finished: finished.promise, release: release.resolve }
}

const app = await startApp(input, [{
    name: 'swipehome-e2e-proposal-transport',
    configureServer(vite) {
      vite.middlewares.use(async (request, response, next) => {
        if (request.method !== 'POST'
          || !/^\/api\/(?:inmuebles\/[^/]+\/propuestas|propuestas\/[^/]+\/decision)$/.test(request.url)) {
          next()
          return
        }
        const entry = { path: request.url }
        mutations.push(entry)
        const fault = nextFault?.path === request.url ? nextFault : null
        if (fault) nextFault = null
        try {
          const body = await readStream(request)
          entry.body = JSON.parse(body)
          if (fault) {
            fault.started.resolve()
            await Promise.race([fault.release, delay(12000, undefined, { ref: false })])
          }
          const upstream = await fetch(backend + request.url, {
            method: request.method,
            headers: { Authorization: request.headers.authorization, 'Content-Type': request.headers['content-type'] },
            body,
          })
          entry.status = upstream.status
          const raw = await upstream.text()
          response.writeHead(fault?.failureStatus ?? upstream.status, { 'Content-Type': 'application/json' })
          response.end(fault?.failureStatus ? JSON.stringify({ error: 'Error temporal. Inténtalo de nuevo.' }) : raw)
          fault?.finished.resolve(entry)
        } catch (error) {
          fault?.started.reject(error)
          fault?.finished.reject(error)
          next(error)
        }
      })
    },
}])
const { chromium, open, pathOf, login, account } = app
const buttonExists = (tab, label) => tab.evaluate((name) =>
  [...document.querySelectorAll('main button')].some((button) => button.innerText.trim() === name), label)

async function buyerCard(seller, buyer) {
  const position = await waitFor(() => seller.evaluate((name) => {
    const cards = [...document.querySelectorAll('.matches-page__list > li')]
    return cards.findIndex((card) => card.innerText.includes(`Comprador/a: Cuenta ${name}\n`)
      || card.innerText.includes(`Comprador/a: Cuenta ${name}\r`)) + 1
  }, buyer), `match de ${buyer}`)
  return `.matches-page__list > li:nth-child(${position})`
}

async function propose(seller, buyer = 'buyer') {
  await seller.click('Enviar propuesta', await buyerCard(seller, buyer))
  await seller.text('Propuesta enviada.')
  await seller.click('Ver propuesta')
  await seller.text('Estado: Pendiente')
  return pathOf(seller)
}

async function buyerDetail(buyer, expectedPath) {
  await buyer.click('Propuestas')
  await buyer.click(`${homeTitle} · Pendiente`)
  await buyer.text('Estado: Pendiente')
  assert.equal(await pathOf(buyer), expectedPath)
}

async function acceptance() {
  const seller = await account('seller')
  const staleSeller = await account('seller')
  const buyer = await account('buyer', { width: 390, height: 844, mobile: true })
  const other = await account('other')
  const explorer = await account('outsider')
  await explorer.text(homeTitle)
  await seller.click('Mis matches')
  await staleSeller.click('Mis matches')
  const staleOtherCard = await buyerCard(staleSeller, 'other')
  assert.equal(await buttonExists(staleSeller, 'Enviar propuesta'), true)

  const path = await propose(seller)
  await assertNoOverflow(seller, 1280)
  await seller.click('Mis matches')
  await seller.text('Hay una propuesta pendiente para esta vivienda.')
  assert.equal(await buttonExists(seller, 'Enviar propuesta'), false)
  await staleSeller.click('Enviar propuesta', staleOtherCard)
  await staleSeller.text('El anuncio o la propuesta ya tiene un estado incompatible.')
  await staleSeller.text('Hay una propuesta pendiente para esta vivienda.')
  assert.equal(await buttonExists(staleSeller, 'Enviar propuesta'), false)

  await buyer.click('Notificaciones')
  await buyer.text('El propietario te ha enviado una propuesta de selección.')
  await buyer.click('Ver propuesta')
  await buyer.text('Estado: Pendiente')
  assert.equal(await pathOf(buyer), path)
  for (const value of ['999.99 €', '65.50 m²', 'Cuenta seller actualizada', 'Condiciones actualizadas', 'Calle Mayor 1']) {
    await buyer.text(value)
  }
  assert.equal(await buttonExists(buyer, 'Cancelar propuesta'), false)
  await assertNoOverflow(buyer, 390)
  await buyer.keyboardClick('Aceptar propuesta')
  await buyer.text('Estado: Aceptada')
  await buyer.text('Vivienda no disponible')
  assert.equal(await buttonExists(buyer, 'Aceptar propuesta'), false)

  await seller.click('Volver al inicio')
  await seller.click('Notificaciones')
  await seller.text('El comprador ha aceptado la propuesta y la vivienda ha quedado cerrada.')
  await seller.click('Ver propuesta')
  await seller.text('Estado: Aceptada')
  assert.equal(await buttonExists(seller, 'Cancelar propuesta'), false)
  await seller.click('Mis matches')
  await seller.text('Vivienda no disponible')
  assert.equal(await buttonExists(seller, 'Enviar propuesta'), false)

  await open(explorer, '/comprador/inicio')
  await explorer.text('No hay viviendas pendientes')
  assert.equal(await explorer.evaluate((title) => document.body.innerText.includes(title), homeTitle), false)
  await other.click('Mis matches')
  await other.text('Vivienda no disponible')
  await open(other, '/mis-matches')
  await other.text('Vivienda no disponible')
  await other.click('Propuestas')
  await other.text('Aún no tienes propuestas.')
  await open(other, path)
  await other.text('Propuesta o candidatura no encontrada.')
  assert.equal(await buttonExists(other, 'Aceptar propuesta'), false)
  await other.click('Notificaciones')
  await other.text('La vivienda ya no está disponible.')
  const notice = await other.evaluate(() => {
    const card = document.querySelector('.notification-card--SELECTION_UNAVAILABLE')
    return { text: card.innerText, links: card.querySelectorAll('a').length }
  })
  assert.match(notice.text, /Piso luminoso/)
  assert.doesNotMatch(notice.text, /Cuenta buyer|Comprador:/)
  assert.equal(notice.links, 0)

  await open(buyer, path)
  await buyer.text('Estado: Aceptada')
  await buyer.click('Salir')
  await waitFor(async () => await pathOf(buyer) === '/', 'cierre de sesión del comprador')
  await delay(1100) // Auth Emulator registra auth_time en segundos.
  await login(buyer, 'buyer')
  await buyer.click('Propuestas')
  await buyer.click(`${homeTitle} · Aceptada`)
  await buyer.text('Estado: Aceptada')
  assert.equal(await pathOf(buyer), path)
}

async function rejection() {
  const seller = await account('seller')
  const buyer = await account('buyer')
  const other = await account('other')
  const explorer = await account('outsider')
  await seller.click('Mis matches')
  const path = await propose(seller)
  await buyerDetail(buyer, path)
  await buyer.keyboardClick('Rechazar propuesta')
  await buyer.text('Estado: Rechazada')
  assert.equal(await buttonExists(buyer, 'Aceptar propuesta'), false)
  await seller.click('Notificaciones')
  await seller.text('El comprador ha rechazado la propuesta.')
  await seller.click('Ver propuesta')
  await seller.text('Estado: Rechazada')
  await open(explorer, '/comprador/inicio')
  await explorer.text(homeTitle)
  await seller.click('Mis matches')
  const newPath = await propose(seller, 'other')
  assert.notEqual(path, newPath)
  await buyerDetail(other, newPath)
  await open(buyer, newPath)
  await buyer.text('Propuesta o candidatura no encontrada.')
}

async function cancellation() {
  const seller = await account('seller')
  const buyer = await account('buyer')
  const explorer = await account('outsider')
  await seller.click('Mis matches')
  const path = await propose(seller)
  await buyerDetail(buyer, path)
  await seller.keyboardClick('Cancelar propuesta')
  await seller.text('Estado: Cancelada')
  await buyer.click('Aceptar propuesta')
  await buyer.text('La propuesta cambió. Comprueba su estado actualizado.')
  await buyer.text('Estado: Cancelada')
  assert.equal(await buttonExists(buyer, 'Aceptar propuesta'), false)
  assert.equal(await buttonExists(buyer, 'Rechazar propuesta'), false)
  assert.equal(mutations.find((entry) => entry.body?.decision === 'ACCEPT')?.status, 409)
  await buyer.click('Notificaciones')
  await buyer.text('El propietario ha cancelado la propuesta.')
  await open(explorer, '/comprador/inicio')
  await explorer.text(homeTitle)
  await seller.click('Mis matches')
  const fresh = await propose(seller)
  assert.notEqual(fresh, path)
}

async function errors() {
  const seller = await account('seller')
  const buyer = await account('buyer')
  await seller.click('Mis matches')
  const card = await buyerCard(seller, 'buyer')
  const send = holdNext(sendPath, 503)
  await seller.evaluate((scope) => {
    const button = document.querySelector(`${scope} button`)
    button.click()
    button.click()
  }, card)
  await send.started
  await seller.text('Enviando propuesta…')
  assert.equal(await seller.evaluate((scope) => document.querySelector(`${scope} button`).disabled, card), true)
  assert.equal(mutations.filter((entry) => entry.path === sendPath).length, 1)
  send.release()
  const committed = await send.finished
  assert.equal(committed.status, 201)
  await seller.text('Error temporal. Inténtalo de nuevo.')
  await open(seller, '/mis-matches')
  await seller.text('Hay una propuesta pendiente para esta vivienda.')
  await seller.click('Reintentar envío')
  await seller.text('Propuesta enviada.')
  assert.deepEqual(mutations.filter((entry) => entry.path === sendPath).map((entry) => entry.status), [201, 200])
  assert.deepEqual(mutations.findLast((entry) => entry.path === sendPath).body, committed.body)
  await seller.click('Ver propuesta')
  const path = await pathOf(seller)
  await buyerDetail(buyer, path)

  const network = { latency: 0, downloadThroughput: -1, uploadThroughput: -1 }
  await buyer.send('Network.emulateNetworkConditions', { ...network, offline: true })
  await buyer.click('Aceptar propuesta')
  await buyer.text('No hay conexión con el servidor. Puedes reintentar la respuesta.')
  await buyer.send('Network.emulateNetworkConditions', { ...network, offline: false })
  const decisionPath = '/api' + path + '/decision'
  assert.equal(mutations.filter((entry) => entry.path === decisionPath).length, 0)
  await seller.click('Actualizar')
  await seller.text('Estado: Pendiente')

  const decision = holdNext(decisionPath, 503)
  await buyer.evaluate(() => {
    const button = [...document.querySelectorAll('main button')].find((node) => node.innerText === 'Aceptar propuesta')
    button.click()
    button.click()
  })
  await decision.started
  await buyer.text('Guardando respuesta…')
  assert.equal(await buyer.evaluate(() => [...document.querySelectorAll('.proposal-actions button')].every((b) => b.disabled)), true)
  assert.equal(mutations.filter((entry) => entry.path === decisionPath).length, 1)
  decision.release()
  assert.equal((await decision.finished).status, 201)
  await buyer.text('Error temporal. Inténtalo de nuevo.')
  await buyer.click('Aceptar propuesta')
  await buyer.text('Estado: Aceptada')
  assert.deepEqual(mutations.filter((entry) => entry.path === decisionPath).map((entry) => entry.status), [201, 200])
}

try {
  console.log(`${scenario} en ${chromium.version}`)
  await { acceptance, rejection, cancellation, errors }[scenario]()
  if (process.env.SWIPEHOME_QA_DEBUG === '1') await chromium.capture(`selection-${scenario}`)
  console.log(`${scenario}: recorrido de navegador correcto`)
} catch (error) {
  await chromium.capture(`selection-${scenario}-failed`)
  throw error
} finally {
  await app.close()
}
