import { createRoot } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { SellerCandidates } from '../src/components/SellerCandidates'
import { PreferenceFilters } from '../src/components/PreferenceFilters'
import { BuyerHome } from '../src/pages/BuyerHome'
import { MatchesPage } from '../src/pages/MatchesPage'
import { ProposalsPage } from '../src/pages/ProposalsPage'
import '../src/index.css'

const components = { SellerCandidates, PreferenceFilters, BuyerHome, MatchesPage, ProposalsPage }
const root = createRoot(document.getElementById('root'))
const deferred = new Map()
const logout = async () => true

window.qa = {
  calls: [],
  unexpected: [],
  replies: {},
  auth: null,
  mount(name, options) {
    this.replies = options.replies
    this.calls = []
    this.unexpected = []
    this.auth = { user: { name: 'Cuenta de prueba', uid: 'fixture', role: options.role || 'BUYER' }, logout }
    const Component = components[name]
    const onApplied = options.refreshFailure ? async () => false : undefined
    root.render(
      <MemoryRouter initialEntries={[options.path || '/']}>
        <Routes>
          <Route path="/propuestas/:selectionId?" element={<Component />} />
          <Route path="*" element={<Component onApplied={onApplied} />} />
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
