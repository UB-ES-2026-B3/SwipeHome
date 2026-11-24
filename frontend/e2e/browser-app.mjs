import assert from 'node:assert/strict'
import { join } from 'node:path'
import { createServer } from 'vite'
import { startChromium, waitFor } from './chromium.mjs'

export async function startApp({ backend, authHost, chrome, emails, password }, plugins = []) {
  assert.match(backend, /^http:\/\/127\.0\.0\.1:\d+$/)
  assert.equal(authHost, '127.0.0.1:9099')
  Object.assign(process.env, {
    VITE_API_TARGET: backend,
    VITE_FIREBASE_PROJECT_ID: 'demo-swipehome-us4',
    VITE_FIREBASE_API_KEY: 'demo-key',
    VITE_FIREBASE_AUTH_DOMAIN: '127.0.0.1',
    VITE_FIREBASE_APP_ID: '1:123456789:web:1234567890',
    VITE_FIREBASE_AUTH_EMULATOR_HOST: authHost,
  })
  const server = await createServer({
    mode: 'qa-e2e',
    envFile: false,
    logLevel: 'error',
    cacheDir: process.env.SWIPEHOME_QA_VITE_CACHE && join(process.env.SWIPEHOME_QA_VITE_CACHE, 'e2e'),
    server: { host: '127.0.0.1', port: 0, hmr: false },
    plugins,
  })
  let chromium
  try {
    await server.listen()
    const origin = `http://127.0.0.1:${server.httpServer.address().port}`
    chromium = await startChromium(chrome)
    const open = (tab, path) => tab.navigate(origin + path)
    const pathOf = (tab) => tab.evaluate(() => location.pathname)

    async function login(tab, name) {
      await open(tab, '/login')
      await tab.fill('input[name=email]', emails[name])
      await tab.fill('input[name=password]', password)
      await tab.click('Iniciar sesión', 'form')
      const roleHome = name.endsWith('seller') ? '/vendedor/inicio' : '/comprador/inicio'
      await waitFor(async () => await pathOf(tab) === roleHome, `iniciar sesión como ${name}`)
      return tab
    }

    return {
      chromium, open, pathOf, login,
      account: async (name, viewport) => login(await chromium.tab(viewport), name),
      async close() {
        try { await chromium.close() } finally { await server.close() }
      },
    }
  } catch (error) {
    try { await chromium?.close() } finally { await server.close() }
    throw error
  }
}

export async function scopeForText(tab, selector, text) {
  const position = await waitFor(() => tab.evaluate((query, expected) =>
    [...document.querySelectorAll(query)].findIndex((element) => element.innerText.includes(expected)) + 1,
  selector, text), `encontrar ${text} en ${selector}`)
  return `${selector}:nth-child(${position})`
}

export async function assertNoOverflow(tab, width) {
  const sizes = await tab.evaluate(() => [innerWidth, document.documentElement.scrollWidth])
  assert.equal(sizes[0], width)
  assert.ok(sizes[1] <= width + 1, `Ancho real ${sizes[1]} para viewport ${width}`)
}
