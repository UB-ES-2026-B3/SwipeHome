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
const candidateList = '.seller-dashboard__candidate-list > li'
const matchesList = '.matches-page__list > li'
const noMatches = 'Aún no tienes matches confirmados.'

async function matches() {
  const buyer = await account('buyer', mobile)
  const other = await account('other')
  const seller = await account('seller')
  const unrelated = await account('other_seller')
  await buyer.text('Piso para rechazar')
  await waitFor(() => buyer.evaluate(() => {
    const photo = document.querySelector('.property-card__gallery img')
    return photo?.naturalWidth > 0 && photo.currentSrc.startsWith('http://127.0.0.1:10000/devstoreaccount1/listings/')
  }), 'foto servida desde Azurite')
  await assertNoOverflow(buyer, 390)
  await buyer.click('No me interesa')
  await buyer.text('Piso para confirmar')
  await buyer.keyboardClick('Me interesa')
  await buyer.text('Interés enviado al vendedor.')
  await buyer.click('Mis matches')
  await buyer.text(noMatches)

  await other.text('Piso para rechazar')
  await other.click('Me interesa')
  await other.text('Interés enviado al vendedor.')
  await seller.click('Actualizar', '[aria-labelledby="candidates-title"]')
  const buyerCard = await scopeForText(seller, candidateList, 'Cuenta buyer')
  const otherCard = await scopeForText(seller, candidateList, 'Cuenta other')
  assert.notEqual(buyerCard, otherCard)
  await unrelated.text('No tienes candidaturas pendientes.')
  await seller.click('Aceptar', buyerCard)
  await seller.text('Match confirmado con Cuenta buyer para Piso para confirmar.')

  await seller.send('Network.emulateNetworkConditions', { ...network, offline: true })
  await seller.click('Rechazar', '[aria-labelledby="candidates-title"]')
  await seller.text('No hay conexión para guardar la decisión.')
  await seller.send('Network.emulateNetworkConditions', { ...network, offline: false })
  await seller.keyboardClick('Rechazar')
  await seller.text('Candidatura de Cuenta other rechazada para Piso para rechazar.')
  await seller.text('No tienes candidaturas pendientes.')

  await seller.click('Mis matches')
  await waitFor(() => seller.evaluate(() => document.querySelector('h1')?.innerText === 'Mis matches'),
    'ruta de matches del vendedor')
  await seller.text('Piso para confirmar')
  assert.equal(await seller.evaluate(() => document.body.innerText.includes('Piso para rechazar')), false)
  await open(buyer, '/mis-matches')
  await buyer.text('Piso para confirmar')
  await open(other, '/mis-matches')
  await other.text(noMatches)
  await unrelated.click('Mis matches')
  await unrelated.text(noMatches)
  await open(buyer, '/notificaciones')
  await buyer.text('Piso para confirmar')
}

async function preferences() {
  const buyer = await account('buyer', mobile)
  const other = await account('other')
  await buyer.text('Piso descartado')
  await buyer.click('No me interesa')
  await buyer.text('Piso luminoso')
  await buyer.click('Filtros')
  await buyer.fill('#filter-price_max', '600')
  await buyer.keyboardClick('Aplicar filtros')
  await buyer.text('Piso asequible')
  await buyer.text('Filtros guardados y aplicados.')
  await assertNoOverflow(buyer, 390)

  await open(other, '/comprador/inicio')
  await other.text('Piso descartado')
  await buyer.click('Mi perfil')
  await buyer.text('Preferencias de viviendas')
  await waitFor(() => buyer.evaluate(() => Number(document.querySelector('#filter-price_max')?.value) === 600), 'filtro guardado en perfil')
  await buyer.fill('#filter-price_min', '800')
  await buyer.click('Aplicar filtros')
  await buyer.text('El mínimo no puede superar el máximo.')
  assert.equal(await buyer.evaluate(() => document.querySelector('#filter-price_min').getAttribute('aria-invalid')), 'true')
  await buyer.click('Cancelar cambios')
  assert.equal(await buyer.evaluate(() => document.querySelector('#filter-price_min').value), '')

  await buyer.send('Network.emulateNetworkConditions', { ...network, offline: true })
  await buyer.fill('#filter-price_max', '100')
  await buyer.click('Aplicar filtros')
  await buyer.text('No hay conexión para guardar tus filtros.')
  await buyer.send('Network.emulateNetworkConditions', { ...network, offline: false })
  await buyer.click('Aplicar filtros')
  await buyer.text('Filtros guardados y aplicados.')
  await open(buyer, '/comprador/inicio')
  await buyer.text('No hay viviendas pendientes')
  await buyer.click('Modificar o restablecer filtros', '.property-explorer__empty-actions')
  await buyer.click('Restablecer filtros', '.preference-filters')
  await buyer.text('Filtros restablecidos')
  await buyer.text('Piso luminoso')
  await open(buyer, '/comprador/inicio')
  await buyer.text('Piso luminoso')
  assert.equal(await buyer.evaluate(() => document.body.innerText.includes('Piso descartado')), false)
}

async function independent() {
  const seller = await account('seller')
  const buyer = await account('buyer')
  const other = await account('other')
  await seller.click('Mis matches')
  await seller.click('Enviar propuesta', await scopeForText(seller, matchesList, 'Cuenta buyer'))
  await seller.text('Propuesta enviada.')
  const second = await scopeForText(seller, matchesList, 'Piso todavía disponible')
  await seller.click('Enviar propuesta', second)
  await waitFor(() => seller.evaluate((row) => document.querySelector(row).innerText.includes('Hay una propuesta pendiente'), second),
    'segunda propuesta registrada')
  await seller.click('Propuestas')
  await seller.text('Piso todavía disponible · Pendiente')
  await seller.text('Piso luminoso · Pendiente')

  await buyer.click('Propuestas')
  await buyer.click('Piso luminoso · Pendiente')
  await buyer.click('Aceptar propuesta')
  await buyer.text('Estado: Aceptada')
  await open(seller, '/propuestas')
  await seller.text('Piso luminoso · Aceptada')
  await seller.text('Piso todavía disponible · Pendiente')
  await other.click('Propuestas')
  await other.click('Piso todavía disponible · Pendiente')
  await other.click('Rechazar propuesta')
  await other.text('Estado: Rechazada')
  await open(seller, '/mis-matches')
  const closed = await scopeForText(seller, matchesList, 'Piso luminoso')
  const openHome = await scopeForText(seller, matchesList, 'Piso todavía disponible')
  assert.match(await seller.evaluate((card) => document.querySelector(card).innerText, closed), /Vivienda no disponible/)
  assert.match(await seller.evaluate((card) => document.querySelector(card).innerText, openHome), /Enviar propuesta/)
}

try {
  console.log(`${scenario} en ${chromium.version}`)
  await { matches, preferences, 'independent-proposals': independent }[scenario]()
  if (process.env.SWIPEHOME_QA_DEBUG === '1') await chromium.capture(scenario)
  console.log(`${scenario}: recorrido de navegador correcto`)
} catch (error) {
  await chromium.capture(`${scenario}-failed`)
  throw error
} finally {
  await app.close()
}
