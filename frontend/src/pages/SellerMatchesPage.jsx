import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { decideCandidate, getActiveProperties, getConfirmedMatches, getPendingCandidates } from '../api/properties'
import { Logo } from '../components/Logo'

const dateFormat = new Intl.DateTimeFormat('es-ES', { dateStyle: 'medium', timeStyle: 'short' })
const priceFormat = new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'EUR', maximumFractionDigits: 2 })
const initialPage = { items: [], cursor: null, loading: true, error: '' }

function propertyLabel({ title, street, city, price }) {
  return [title, street, city, price > 0 ? `${priceFormat.format(price)}/mes` : ''].filter(Boolean).join(' · ')
}

function MatchSection({ pending = false, propertyId, saving, onDecision }) {
  const [page, setPage] = useState(initialPage)
  const [decisionError, setDecisionError] = useState(null)
  const request = useRef(null)
  const title = pending ? 'Pendientes' : 'Matches confirmados'
  const sectionId = pending ? 'seller-pending' : 'seller-confirmed'
  const expectedStatus = pending ? 'PENDING' : 'CONFIRMED'
  const fetchPage = pending ? getPendingCandidates : getConfirmedMatches

  const load = useCallback((cursor = null) => {
    if (request.current) return
    const controller = new AbortController()
    request.current = controller
    fetchPage(cursor, controller.signal, propertyId)
      .then(({ ok, data }) => {
        if (controller.signal.aborted) return
        if (!ok || !Array.isArray(data?.items)) throw new Error(data?.error || 'No se pudo cargar la lista.')
        const items = data.items.filter((item) => item.status === expectedStatus)
        setPage((previous) => ({
          items: cursor ? [...previous.items, ...items] : items,
          cursor: data.next_cursor ?? null,
          loading: false,
          error: '',
        }))
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setPage((previous) => ({ ...previous, loading: false, error: error.message || 'No se pudo cargar la lista.' }))
        }
      })
      .finally(() => {
        if (request.current === controller) request.current = null
      })
  }, [expectedStatus, fetchPage, propertyId])

  useEffect(() => {
    load()
    return () => {
      request.current?.abort()
      request.current = null
    }
  }, [load])

  function loadMore() {
    setPage((previous) => ({ ...previous, loading: true, error: '' }))
    load(page.cursor)
  }

  async function submit(item, decision) {
    setDecisionError(null)
    try {
      if (await onDecision(item.id, decision)) {
        setPage((previous) => ({ ...previous, items: previous.items.filter((entry) => entry.id !== item.id) }))
      }
    } catch (error) {
      setDecisionError({ id: item.id, message: error.message })
    }
  }

  return (
    <section className="seller-matches__section" aria-labelledby={sectionId}>
      <h2 id={sectionId}>{title}</h2>
      {page.items.length > 0 && (
        <ul className="seller-dashboard__notifications-list" role="list">
          {page.items.map((item) => {
            const buyer = item.buyer?.name || 'Comprador sin nombre'
            const listing = item.listing?.title || 'Vivienda sin título'
            const timestamp = pending ? item.created_at : item.confirmed_at
            const date = timestamp && new Date(timestamp)
            return (
              <li className="seller-dashboard__notification seller-matches__item" key={item.id}>
                <div className="seller-matches__summary">
                  <h3>{buyer}</h3>
                  <p>{listing}</p>
                  {date && !Number.isNaN(date.getTime()) && (
                    <p className="seller-matches__date">{pending ? 'Interés: ' : 'Confirmación: '}<time dateTime={timestamp}>{dateFormat.format(date)}</time></p>
                  )}
                </div>
                {pending && (
                  <div className="seller-matches__actions" role="group" aria-label={`Candidatura de ${buyer} para ${listing}`}>
                    <button className="btn btn--dark" type="button" disabled={saving || page.loading}
                      aria-label={`Me interesa: ${buyer}, ${listing}`} onClick={() => submit(item, 'LIKE')}>Me interesa</button>
                    <button className="btn btn--ghost" type="button" disabled={saving || page.loading}
                      aria-label={`No me interesa: ${buyer}, ${listing}`} onClick={() => submit(item, 'PASS')}>No me interesa</button>
                  </div>
                )}
                {decisionError?.id === item.id && <p className="seller-dashboard__message--error" role="alert">{decisionError.message}</p>}
              </li>
            )
          })}
        </ul>
      )}
      {page.loading && <p className="seller-dashboard__message" role="status">Cargando {title.toLowerCase()}…</p>}
      {page.error && (
        <div className="seller-dashboard__message seller-dashboard__message--error">
          <p role="alert">{page.error}</p>
          <button type="button" className="btn btn--ghost" onClick={loadMore}>Reintentar</button>
        </div>
      )}
      {!page.loading && !page.error && !page.items.length && !page.cursor && (
        <p className="seller-dashboard__message">{pending ? 'No tienes candidaturas pendientes.' : 'Todavía no tienes matches confirmados.'}</p>
      )}
      {page.cursor && !page.loading && !page.error && (
        <button type="button" className="btn btn--ghost" disabled={saving} onClick={loadMore}>Cargar más</button>
      )}
    </section>
  )
}

export function SellerMatchesPage() {
  const [properties, setProperties] = useState(null)
  const [filterError, setFilterError] = useState('')
  const [filterAttempt, setFilterAttempt] = useState(0)
  const [propertyId, setPropertyId] = useState('')
  const [decisionState, setDecisionState] = useState({ saving: false, message: '' })
  const [confirmedVersion, setConfirmedVersion] = useState(0)
  const decisionLock = useRef(false)
  const selectedProperty = properties?.find((property) => property.id === propertyId)

  useEffect(() => {
    const controller = new AbortController()
    getActiveProperties(controller.signal)
      .then(({ ok, data }) => {
        if (controller.signal.aborted) return
        if (!ok || !Array.isArray(data?.properties)) throw new Error()
        setProperties(data.properties)
      })
      .catch(() => {
        if (!controller.signal.aborted) setFilterError('No se pudieron cargar tus viviendas para filtrar.')
      })
    return () => controller.abort()
  }, [filterAttempt])

  function changeProperty(id) {
    setPropertyId(id)
    setDecisionState({ saving: false, message: '' })
  }

  async function saveDecision(matchId, decision) {
    if (decisionLock.current) return false
    decisionLock.current = true
    setDecisionState({ saving: true, message: 'Guardando decisión…' })
    try {
      const { ok, status, data } = await decideCandidate(matchId, decision)
      const confirmed = decision === 'LIKE'
      if (status === 409) {
        setConfirmedVersion((version) => version + 1)
        setDecisionState({ saving: false, message: 'Esta candidatura ya no está pendiente.' })
        return true
      }
      if (!ok || data?.id !== matchId || data?.status !== (confirmed ? 'CONFIRMED' : 'REJECTED')) {
        throw new Error(data?.error || 'El servidor no pudo guardar la decisión.')
      }
      if (confirmed) setConfirmedVersion((version) => version + 1)
      setDecisionState({ saving: false, message: confirmed ? 'Match confirmado.' : 'Candidatura rechazada.' })
      return true
    } catch {
      setDecisionState({ saving: false, message: '' })
      throw new Error('No se pudo guardar la decisión. Inténtalo de nuevo.')
    } finally {
      decisionLock.current = false
    }
  }

  return (
    <main className="seller-dashboard">
      <header className="home-page__header">
        <Logo size="sm" to="/vendedor/inicio" />
        <Link className="btn btn--ghost uniform-action" to="/vendedor/inicio">Volver al inicio</Link>
      </header>
      <div className="seller-dashboard__content seller-matches">
        <h1 className="home-page__title">Candidatos y matches</h1>
        <div className="seller-matches__filter">
          <label htmlFor="seller-match-property">Filtrar por vivienda</label>
          <div className="seller-matches__filter-controls">
            <select id="seller-match-property" value={propertyId} disabled={!properties || decisionState.saving}
              onChange={(event) => changeProperty(event.target.value)}>
              <option value="">Todas mis viviendas</option>
              {properties?.map((property) => <option key={property.id} value={property.id}>{propertyLabel(property)}</option>)}
            </select>
            {selectedProperty && (
              <button type="button" className="btn btn--ghost" disabled={decisionState.saving}
                onClick={() => changeProperty('')}>Quitar filtro</button>
            )}
          </div>
          {selectedProperty && <p className="seller-matches__filter-status" role="status">Mostrando: {selectedProperty.title}</p>}
          {filterError && (
            <div className="seller-matches__actions">
              <span role="alert">{filterError}</span>
              <button type="button" className="btn btn--ghost" onClick={() => {
                setFilterError('')
                setFilterAttempt((attempt) => attempt + 1)
              }}>Reintentar filtro</button>
            </div>
          )}
        </div>
        <p className="seller-matches__feedback" role="status">{decisionState.message}</p>
        <div className="seller-matches__sections">
          <MatchSection key={`pending:${propertyId}`} pending propertyId={propertyId} saving={decisionState.saving} onDecision={saveDecision} />
          <MatchSection key={`confirmed:${propertyId}:${confirmedVersion}`} propertyId={propertyId} />
        </div>
      </div>
    </main>
  )
}