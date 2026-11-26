import assert from 'node:assert/strict'
import { text as readStream } from 'node:stream/consumers'
import { assertNoOverflow, scopeForText, startApp } from './browser-app.mjs'
import { waitFor } from './chromium.mjs'

const input = JSON.parse(await readStream(process.stdin))
const { scenario } = input
const app = await startApp(input)
const { account, chromium, open } = app
const mobile = { width: 390, height: 844, mobile: true }
const network = { latency: 0, downloadThroughput: -1, uploadThroughput: -1 }

const noMatches = 'Todavía no tienes matches confirmados.'
const sellerPath = '/vendedor/matches'
const buyerPath = '/comprador/matches'
const buyerProposals = '/comprador/propuestas'

async function selectHome(seller, title) {
  await waitFor(() => seller.evaluate(() => Boolean(document.querySelector('.seller-matches__property h3, .seller-matches__property .property-card__body h2'))), 'vivienda cargada')
  while (await seller.evaluate(() => !document.querySelector('[aria-label="Vivienda anterior"]').disabled)) {
    await seller.click('Vivienda anterior')
  }
  for (let step = 0; step < 3; step++) {
    if (await seller.evaluate((name) => document.querySelector('.seller-matches__property .property-card__body').innerText.includes(name), title)) return
    await seller.click('Vivienda siguiente')
  }
  throw new Error('Vivienda ausente: ' + title)
}

async function matches() {
  const buyer = await account('buyer', mobile)
  const other = await account('other')
  const seller = await account('seller')
  const unrelated = await account('other_seller')
  await buyer.text('Piso para rechazar')
  await waitFor(() => buyer.evaluate(() => [...document.images].some(photo =>
    photo.naturalWidth > 0 && photo.currentSrc.startsWith('http://127.0.0.1:10000/devstoreaccount1/listings/'))), 'foto servida desde Azurite')
  await assertNoOverflow(buyer, 390)
  await buyer.click('No me interesa')
  await buyer.text('Piso para confirmar')
  await buyer.keyboardClick('Me interesa')
  await buyer.text('Interés enviado')
  await open(buyer, buyerPath)
  await buyer.text(noMatches)
  await other.text('Piso para rechazar')
  await other.click('Me interesa')
  await other.text('Interés enviado')
  await open(seller, sellerPath)
  await selectHome(seller, 'Piso para rechazar')
  await open(unrelated, sellerPath)
  await unrelated.text('Todavía no tienes viviendas publicadas.')
  const rejection = 'No me interesa: Cuenta other, Piso para rechazar'
  await seller.send('Network.emulateNetworkConditions', { ...network, offline: true })
  await seller.click(rejection)
  await seller.text('No se pudo guardar la decisión.')
  await seller.send('Network.emulateNetworkConditions', { ...network, offline: false })
  await seller.keyboardClick(rejection)
  await seller.text('Candidatura rechazada.')
  await selectHome(seller, 'Piso para confirmar')
  await seller.click('Me interesa: Cuenta buyer, Piso para confirmar')
  await seller.text('Match confirmado.')
  await open(buyer, buyerPath)
  await buyer.text('Piso para confirmar')
  await open(other, buyerPath)
  await other.text(noMatches)
  await open(seller, '/notificaciones')
  await seller.text('Piso para confirmar')
}

async function preferences() {
  const buyer = await account('buyer', mobile)
  const other = await account('other')
  await buyer.text('Piso descartado')
  await buyer.click('No me interesa')
  await buyer.click('Filtros')
  await buyer.fill('#pref-max-price', '600')
  await buyer.keyboardClick('Aplicar filtros')
  await buyer.text('Piso asequible')
  await assertNoOverflow(buyer, 390)
  await other.text('Piso descartado')

  await buyer.click('Mi perfil')
  await buyer.click('Editar preferencias')
  await waitFor(() => buyer.evaluate(() => Number(document.querySelector('#pref-max-price')?.value) === 600), 'filtro guardado en perfil')
  await buyer.fill('#pref-min-price', '800')
  await buyer.click('Aplicar filtros')
  await buyer.text('Debe ser mayor o igual al precio mínimo.')
  await buyer.click('Cancelar', '[role=dialog]')
  await waitFor(() => buyer.evaluate(() => !document.querySelector('[role=dialog]')), 'cancelar las preferencias')
  await buyer.click('Editar preferencias')
  await waitFor(() => buyer.evaluate(() => Boolean(document.querySelector('#pref-min-price'))), 'preferencias abiertas')
  assert.equal(await buyer.evaluate(() => document.querySelector('#pref-min-price').value), '')

  await buyer.send('Network.emulateNetworkConditions', { ...network, offline: true })
  await buyer.fill('#pref-max-price', '100')
  await buyer.click('Aplicar filtros')
  await buyer.text('No hay conexión con el servidor.')
  await buyer.send('Network.emulateNetworkConditions', { ...network, offline: false })
  await buyer.click('Aplicar filtros')
  await waitFor(() => buyer.evaluate(() => !document.querySelector('#pref-max-price')), 'modal cerrada después del guardado')
  await open(buyer, '/comprador/inicio')
  await buyer.text('No hay más viviendas por explorar')
  await buyer.click('Filtros')
  await buyer.click('Restablecer filtros')
  await buyer.text('Filtros restablecidos')
  await buyer.click('Cancelar', '[role=dialog]')
  await buyer.text('Piso luminoso')
  await open(buyer, '/comprador/inicio')
  await buyer.text('Piso luminoso')
  assert.equal(await buyer.evaluate(() => document.body.innerText.includes('Piso descartado')), false)
}

async function independent() {
  const seller = await account('seller')
  const buyer = await account('buyer')
  const other = await account('other')
  await open(seller, sellerPath)
  await selectHome(seller, 'Piso luminoso')
  await seller.click('Matches confirmados')
  await seller.click('Proponer selección: Cuenta buyer, Piso luminoso')
  await seller.text('Propuesta enviada.')
  await selectHome(seller, 'Piso todavía disponible')
  await seller.click('Matches confirmados')
  await seller.click('Proponer selección: Cuenta other, Piso todavía disponible')
  await seller.text('Pendiente')

  await open(buyer, buyerProposals)
  await buyer.text('Piso luminoso')
  await buyer.click('Aceptar')
  await buyer.text('Aceptada')
  await open(other, buyerProposals)
  await other.text('Piso todavía disponible')
  await other.text('Pendiente')
  await other.click('Rechazar')
  await other.text('Rechazada')
  await open(buyer, buyerPath)
  await buyer.text('Anuncio cerrado')
  await open(other, buyerPath)
  const second = await scopeForText(other, '.buyer-matches__list > li', 'Piso todavía disponible')
  assert.equal(await other.evaluate(row => document.querySelector(row).innerText.includes('Anuncio cerrado'), second), false)
}

try {
  await { matches, preferences, 'independent-proposals': independent }[scenario]()
  console.log(scenario + ': recorrido de navegador correcto')
} catch (error) {
  await chromium.capture(scenario + '-failed')
  throw error
} finally {
  await app.close()
}
