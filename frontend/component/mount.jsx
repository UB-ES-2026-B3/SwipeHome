import { createRoot } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { SellerMatchesPage } from '../src/pages/SellerMatchesPage'
import { SearchPreferencesForm } from '../src/components/SearchPreferencesForm'
import { BuyerHome } from '../src/pages/BuyerHome'
import { BuyerMatchesPage } from '../src/pages/BuyerMatchesPage'
import { BuyerProposalsPage } from '../src/pages/BuyerProposalsPage'
import '../src/index.css'

const components = { SellerMatchesPage, SearchPreferencesForm, BuyerHome, BuyerMatchesPage, BuyerProposalsPage }
const root = createRoot(document.getElementById('root'))
const deferred = new Map()
const logout = async () => true
window.confirm = () => true

window.qa = {
  calls: [],
  unexpected: [],
  replies: {},
  auth: null,
  mount(name, options) {
    this.replies = options.replies
    this.calls = []
    this.unexpected = []
    this.auth = { user: { name: 'Cuenta de prueba', uid: 'fixture', role: options.role || 'BUYER' }, logout, expireSession: logout }
    const Component = components[name]
    root.render(
      <MemoryRouter initialEntries={[options.path || '/']}>
        <Routes>
          <Route path="*" element={<Component />} />
        </Routes>
      </MemoryRouter>,
    )
  },
  async call(name, args) {
    this.calls.push({ name, args })
    const response = this.replies[name]?.shift()
    if (!response) {
      this.unexpected.push(name)
      throw new Error(`Sin respuesta configurada para ${name}`)
    }
    if (response.hold) {
      const gate = Promise.withResolvers()
      deferred.set(response.hold, gate.resolve)
      await gate.promise
    }
    return { ok: response.status >= 200 && response.status < 300, ...response }
  },
  release(name) {
    const release = deferred.get(name)
    if (!release) throw new Error(`La petición ${name} todavía no se inició.`)
    deferred.delete(name)
    release()
  },
}
