import { spawn } from 'node:child_process'
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, relative } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'

export async function waitFor(check, description, timeout = 15000) {
  const deadline = Date.now() + timeout
  do {
    const result = await check()
    if (result) return result
    await delay(75)
  } while (Date.now() < deadline)
  throw new Error(`Tiempo agotado: ${description}`)
}

export async function startChromium(executable) {
  const profile = await mkdtemp(join(tmpdir(), 'swipehome-chrome-'))
  const visual = globalThis.process.env.SWIPEHOME_QA_VISUAL === '1'
  const process = spawn(executable, [
    ...(visual ? [] : ['--headless']), '--disable-gpu', '--disable-background-networking',
    '--disable-component-update', '--no-first-run', '--no-default-browser-check',
    '--no-proxy-server', '--remote-debugging-port=0',
    '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1',
    `--user-data-dir=${profile}`, 'about:blank',
  ], { windowsHide: !visual, stdio: ['ignore', 'ignore', 'pipe'] })
  let stderr = ''
  let launchError
  process.on('error', (error) => { launchError = error })
  process.stderr.setEncoding('utf8')
  process.stderr.on('data', (line) => { stderr = (stderr + line).slice(-2000) })
  let socket

  async function close() {
    socket?.close()
    if (process.pid && process.exitCode === null) {
      const exiting = new Promise((resolve) => process.once('exit', resolve))
      process.kill()
      await Promise.race([exiting, delay(3000)])
    }
    if (/^swipehome-chrome-[^/\\]+$/.test(relative(tmpdir(), profile))) {
      await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 })
    }
  }

  try {
    const address = await waitFor(async () => {
      if (launchError) throw launchError
      if (process.exitCode !== null) throw new Error(stderr || 'Chromium se cerró al arrancar.')
      return readFile(join(profile, 'DevToolsActivePort'), 'utf8').catch(() => null)
    }, 'Chromium en modo headless')
    const [port] = address.split('\n')
    const version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json()
    socket = new WebSocket(version.webSocketDebuggerUrl)
    await new Promise((resolve, reject) => {
      socket.addEventListener('open', resolve, { once: true })
      socket.addEventListener('error', reject, { once: true })
    })
    const pending = new Map()
    const tabs = []
    const exceptions = new Map()
    let sequence = 0
    socket.addEventListener('message', ({ data }) => {
      const { id, result, error, sessionId, method, params } = JSON.parse(data)
      if (method === 'Runtime.exceptionThrown' && exceptions.has(sessionId)) {
        const { text, exception } = params.exceptionDetails
        const recent = exceptions.get(sessionId)
        recent.push(exception?.description || text)
        if (recent.length > 10) recent.shift()
      }
      const request = pending.get(id)
      if (!request) return
      pending.delete(id)
      clearTimeout(request.timeout)
      if (error) request.reject(new Error(error.message))
      else request.resolve(result)
    })
    socket.addEventListener('close', () => {
      for (const request of pending.values()) {
        clearTimeout(request.timeout)
        request.reject(new Error(`DevTools se desconectó durante ${request.method}. ${stderr}`))
      }
      pending.clear()
    })

    function call(method, params = {}, sessionId) {
      const id = ++sequence
      const result = Promise.withResolvers()
      const timeout = setTimeout(() => {
        pending.delete(id)
        result.reject(new Error(`DevTools no respondió a ${method}. ${stderr}`))
      }, 10000)
      pending.set(id, { ...result, method, timeout })
      socket.send(JSON.stringify({ id, method, params, sessionId }))
      return result.promise
    }

    async function tab({ width = 1280, height = 900, mobile = false } = {}) {
      const { browserContextId } = await call('Target.createBrowserContext', { disposeOnDetach: true })
      const { targetId } = await call('Target.createTarget', { browserContextId, url: 'about:blank' })
      const { sessionId } = await call('Target.attachToTarget', { targetId, flatten: true })
      const send = (method, params) => call(method, params, sessionId)
      const errors = []
      exceptions.set(sessionId, errors)
      await send('Runtime.enable')
      await send('Network.enable')
      await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile })

      async function evaluate(expression, ...args) {
        const encoded = args.map((arg) => JSON.stringify(arg)).join(',')
        const { result, exceptionDetails } = await send('Runtime.evaluate', {
          expression: `(${expression})(${encoded})`, returnByValue: true, awaitPromise: true,
        })
        if (exceptionDetails) throw new Error(exceptionDetails.exception?.description || exceptionDetails.text)
        return result.value
      }

      async function navigate(url) {
        if (!url.startsWith('http://127.0.0.1:')) throw new Error('El navegador de QA solo navega en loopback.')
        const previous = await evaluate(() => performance.timeOrigin)
        const { errorText } = await send('Page.navigate', { url })
        if (errorText) throw new Error(errorText)
        await waitFor(() => evaluate((old) => performance.timeOrigin !== old, previous), `navegar a ${url}`)
      }

      async function text(value) {
        return waitFor(() => evaluate((expected) => document.body?.innerText.includes(expected), value), value)
      }

      async function click(label, scope = 'main') {
        const point = await waitFor(() => evaluate((value, selector) => {
          const element = [...document.querySelectorAll(`${selector} :is(button,a)`)]
            .find((node) => (node.getAttribute('aria-label') || node.innerText.trim()) === value && !node.disabled)
          if (!element) return false
          element.scrollIntoView({ block: 'center' })
          const bounds = element.getBoundingClientRect()
          return bounds.width && bounds.height && { x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2 }
        }, label, scope), `pulsar ${label}`)
        await send('Page.bringToFront')
        await send('Input.dispatchMouseEvent', { type: 'mousePressed', button: 'left', clickCount: 1, ...point })
        await send('Input.dispatchMouseEvent', { type: 'mouseReleased', button: 'left', clickCount: 1, ...point })
      }

      async function key(name, code) {
        await send('Page.bringToFront')
        const event = { key: name, code: name, windowsVirtualKeyCode: code }
        await send('Input.dispatchKeyEvent', name === 'Enter'
          ? { type: 'keyDown', text: '\r', unmodifiedText: '\r', ...event }
          : { type: 'rawKeyDown', ...event })
        await send('Input.dispatchKeyEvent', { type: 'keyUp', ...event })
      }

      async function keyboardClick(label) {
        for (let tabIndex = 0; tabIndex < 25; tabIndex++) {
          await key('Tab', 9)
          if (await evaluate((expected) => {
            const node = document.activeElement
            return (node.getAttribute('aria-label') || node.innerText.trim()) === expected
          }, label)) {
            await key('Enter', 13)
            return
          }
        }
        throw new Error(`El control «${label}» quedó fuera del orden de tabulación.`)
      }

      async function fill(selector, value) {
        await waitFor(() => evaluate((field) => {
          const input = document.querySelector(field)
          input?.focus()
          return Boolean(input)
        }, selector), selector)
        await send('Page.bringToFront')
        await send('Input.dispatchKeyEvent', { type: 'rawKeyDown', key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65, modifiers: 2 })
        await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65, modifiers: 2 })
        await key('Backspace', 8)
        if (value) await send('Input.insertText', { text: value })
      }

      const page = { send, evaluate, navigate, text, click, keyboardClick, fill, key, errors }
      tabs.push(page)
      return page
    }

    async function capture(label) {
      const output = globalThis.process.env.SWIPEHOME_QA_ARTIFACTS
      if (!output) return
      await mkdir(output, { recursive: true })
      const name = label.replace(/[^a-z0-9._-]/gi, '-')
      for (const [index, page] of tabs.entries()) {
        try {
          const base = join(output, `${name}-${index + 1}`)
          const { data } = await page.send('Page.captureScreenshot', { format: 'png' })
          const dom = await page.evaluate(() => ({ url: location.href, text: document.body?.innerText }))
          await Promise.all([
            writeFile(base + '.png', Buffer.from(data, 'base64')),
            writeFile(base + '.json', JSON.stringify({ ...dom, errors: page.errors }, null, 2)),
          ])
        } catch (error) {
          console.error('No se pudo obtener un artefacto del navegador:', error.message)
        }
      }
      console.log(`Artefactos de ${label} en ${output}`)
    }

    return { tab, close, capture, version: version.Browser }
  } catch (error) {
    await close()
    throw error
  }
}
