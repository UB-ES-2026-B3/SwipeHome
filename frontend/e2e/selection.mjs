import assert from 'node:assert/strict'
import { text as readStream } from 'node:stream/consumers'
import { setTimeout as delay } from 'node:timers/promises'
import { assertNoOverflow, startApp } from './browser-app.mjs'
import { waitFor } from './chromium.mjs'

const input = JSON.parse(await readStream(process.stdin))
const { scenario, backend } = input

const homeTitle = 'Piso luminoso'
const sendPath = '/api/propuestas'
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
          || !/^\/api\/propuestas(?:\/[^/]+\/(?:aceptar|rechazar|cancelar))?$/.test(request.url)) {
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
          entry.response = JSON.parse(raw)
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

const { chromium, open, login, account } = app
const sellerPath = '/vendedor/matches'
const buyerPath = '/comprador/propuestas'
const proposalButton = (buyer) => 'Proponer selección: Cuenta ' + buyer + ', ' + homeTitle
const cancelButton = 'Cancelar propuesta: Cuenta buyer, ' + homeTitle
const network = { latency: 0, downloadThroughput: -1, uploadThroughput: -1 }

async function sellerView(seller) {
  await open(seller, sellerPath)
  await seller.click('Matches confirmados')
}

async function propose(seller, who = 'buyer') {
  await seller.click(proposalButton(who))
  await seller.text('Propuesta enviada.')
  await seller.text('Pendiente')
}

async function accept(buyer) {
  await buyer.keyboardClick('Aceptar')
  await buyer.text('Aceptada')
  await buyer.text('Anuncio cerrado')
}

async function acceptance() {
  const seller = await account('seller')
  const stale = await account('seller')
  const buyer = await account('buyer', { width: 390, height: 844, mobile: true })
  const other = await account('other')
  const explorer = await account('outsider')
  await explorer.text(homeTitle)
  await sellerView(stale)
  await sellerView(seller)
  await propose(seller)
  await stale.click(proposalButton('other'))
  await stale.text('La situación de la vivienda ha cambiado.')
  await stale.text('Pendiente')
  await open(buyer, '/notificaciones')
  await buyer.text('Has recibido una propuesta de selección')
  await open(buyer, buyerPath)
  await buyer.text('Pendiente')
  await buyer.text('Cuenta seller actualizada')
  await buyer.click('Ver vivienda')
  await buyer.text('Condiciones actualizadas')
  await assertNoOverflow(buyer, 390)
  await accept(buyer)
  await open(seller, '/notificaciones')
  await seller.text('El comprador ha aceptado tu propuesta')
  await sellerView(seller)
  await seller.text('Anuncio cerrado')
  await open(explorer, '/comprador/inicio')
  await explorer.text('No hay más viviendas por explorar')
  await open(other, '/comprador/matches')
  await other.text('Anuncio cerrado')
  await open(other, buyerPath)
  await other.text('Todavía no tienes propuestas recibidas.')
  await open(other, '/notificaciones')
  await other.text('La vivienda ya no está disponible')
  await open(buyer, '/comprador/inicio')
  await buyer.click('Cerrar sesión')
  await waitFor(() => buyer.evaluate(() => location.pathname === '/'), 'cierre de sesión')
  await login(buyer, 'buyer')
  await open(buyer, buyerPath)
  await buyer.text('Aceptada')
}

async function rejection() {
  const seller = await account('seller')
  const buyer = await account('buyer')
  const other = await account('other')
  const explorer = await account('outsider')
  await sellerView(seller)
  await propose(seller)
  await open(buyer, buyerPath)
  await buyer.text('Pendiente')
  await buyer.keyboardClick('Rechazar')
  await buyer.text('Rechazada')
  await open(seller, '/notificaciones')
  await seller.text('El comprador ha rechazado tu propuesta')
  await open(explorer, '/comprador/inicio')
  await explorer.text(homeTitle)
  await sellerView(seller)
  await propose(seller, 'other')
  await open(other, buyerPath)
  await other.text('Pendiente')
}

async function cancellation() {
  const seller = await account('seller')
  const buyer = await account('buyer')
  const explorer = await account('outsider')
  await sellerView(seller)
  await propose(seller)
  await open(buyer, buyerPath)
  await buyer.text('Pendiente')
  await seller.keyboardClick(cancelButton)
  await seller.text('Propuesta cancelada.')
  await buyer.click('Aceptar')
  await buyer.text('La propuesta ha cambiado.')
  await buyer.text('Cancelada')
  await open(buyer, '/notificaciones')
  await buyer.text('El propietario ha cancelado tu propuesta')
  await open(explorer, '/comprador/inicio')
  await explorer.text(homeTitle)
  await sellerView(seller)
  await propose(seller)
}

async function errors() {
  const seller = await account('seller')
  const buyer = await account('buyer')
  await sellerView(seller)
  const send = holdNext(sendPath, 503)
  await seller.click(proposalButton('buyer'))
  await send.started
  await seller.text('Enviando propuesta')
  assert.equal(await seller.evaluate(() => [...document.querySelectorAll('#seller-panel-confirmed li button')].filter(b => b.textContent === 'Proponer selección').every(b => b.disabled)), true)
  send.release()
  const first = await send.finished
  assert.equal(first.status, 201)
  await seller.text('No se pudo confirmar el envío.')
  await seller.click(proposalButton('buyer'))
  await seller.text('Propuesta enviada.')
  assert.deepEqual(mutations.slice(0, 2).map(({ status }) => status), [201, 200])
  assert.deepEqual(mutations[0].body, mutations[1].body)

  await open(buyer, buyerPath)
  await buyer.text('Pendiente')
  await buyer.send('Network.emulateNetworkConditions', { ...network, offline: true })
  await buyer.click('Aceptar')
  await buyer.text('No se pudo confirmar la respuesta.')
  await buyer.send('Network.emulateNetworkConditions', { ...network, offline: false })
  const proposalId = first.response.id
  const path = '/api/propuestas/' + proposalId + '/aceptar'
  const acceptFault = holdNext(path, 503)
  await buyer.click('Aceptar')
  await acceptFault.started
  assert.equal(await buyer.evaluate(() => [...document.querySelectorAll('.buyer-proposals__card button')].filter(b => ['Aceptar', 'Rechazar'].includes(b.textContent)).every(b => b.disabled)), true)
  acceptFault.release()
  assert.equal((await acceptFault.finished).status, 200)
  await buyer.text('No se pudo confirmar la respuesta.')
  await accept(buyer)
  assert.deepEqual(mutations.filter(({ path: route }) => route === path).map(({ status }) => status), [200, 200])
}

try {
  await { acceptance, rejection, cancellation, errors }[scenario]()
  console.log(scenario + ': recorrido de navegador correcto')
} catch (error) {
  await chromium.capture(scenario + '-failed')
  throw error
} finally {
  await app.close()
}
