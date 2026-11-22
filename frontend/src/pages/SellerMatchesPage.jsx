import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { createProposal, decideCandidate, getActiveProperties, getConfirmedMatches, getPendingCandidates, getProposals, resolveProposal } from '../api/properties'
import { Logo } from '../components/Logo'
import { PropertyDetails, PropertyGallery } from '../components/PropertyDetails'
import { useAuth } from '../hooks/useAuth'

const dateFormat = new Intl.DateTimeFormat('es-ES', { dateStyle: 'medium', timeStyle: 'short' })
const initialPage = { items: [], cursor: null, loading: true, error: '' }
const proposalLabels = { PENDING: 'Pendiente', ACCEPTED: 'Aceptada', REJECTED: 'Rechazada', CANCELLED: 'Cancelada' }

async function loadAllPages(fetchPage, signal, propertyId) {
  const items = []
  const seen = new Set()
  let cursor = null
  do {
    const result = await fetchPage(cursor, signal, propertyId)
    if (result.status === 401) throw Object.assign(new Error('Sesión caducada.'), { status: 401 })
    if (!result.ok || !Array.isArray(result.data?.items)) throw new Error('No se pudieron cargar las propuestas.')
    items.push(...result.data.items)
    cursor = result.data.next_cursor || null
    if (cursor && seen.has(cursor)) throw new Error('No se pudieron cargar las propuestas.')
    if (cursor) seen.add(cursor)
  } while (cursor)
  return items
}

function MatchSection({ pending = false, propertyId, saving, onDecision, expireSession, selection, onPropose }) {
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
      .then(({ ok, status, data }) => {
        if (controller.signal.aborted) return
        if (status === 401) {
          expireSession().catch(() => setPage((previous) => ({ ...previous, loading: false, error: 'Tu sesión ha caducado. Inicia sesión de nuevo.' })))
          return
        }
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
  }, [expectedStatus, expireSession, fetchPage, propertyId])

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
      if (await onDecision(item.id, decision) === 'saved') {
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
                {!pending && selection && !selection.loading && !selection.error && selection.canPropose && (
                  <button className="btn btn--ghost" type="button" disabled={saving}
                    aria-label={`Proponer selección: ${buyer}, ${listing}`}
                    onClick={() => onPropose(item)}>Proponer selección</button>
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
  const { expireSession } = useAuth()
  const [properties, setProperties] = useState(null)
  const [filterError, setFilterError] = useState('')
  const [filterAttempt, setFilterAttempt] = useState(0)
  const [propertyIndex, setPropertyIndex] = useState(0)
  const [decisionState, setDecisionState] = useState({ saving: false, message: '' })
  const [confirmedVersion, setConfirmedVersion] = useState(0)
  const [pendingVersion, setPendingVersion] = useState(0)
  const [selectionVersion, setSelectionVersion] = useState(0)
  const [selection, setSelection] = useState({ loading: true, error: '', items: [], candidates: [] })
  const [dragOffset, setDragOffset] = useState(0)
  const [dragging, setDragging] = useState(false)
  const pointer = useRef(null)
  const decisionLock = useRef(false)
  const requestIds = useRef(new Map())
  const currentIndex = Math.min(propertyIndex, Math.max((properties?.length || 1) - 1, 0))
  const selectedProperty = properties?.[currentIndex]
  const propertyId = selectedProperty?.id

  useEffect(() => {
    const controller = new AbortController()
    getActiveProperties(controller.signal)
      .then(({ ok, status, data }) => {
        if (controller.signal.aborted) return
        if (status === 401) {
          expireSession().catch(() => setFilterError('Tu sesión ha caducado. Inicia sesión de nuevo.'))
          return
        }
        if (!ok || !Array.isArray(data?.properties)) throw new Error()
        setFilterError('')
        setProperties(data.properties)
      })
      .catch(() => {
        if (!controller.signal.aborted) setFilterError('No se pudieron cargar tus viviendas para filtrar.')
      })
    return () => controller.abort()
  }, [expireSession, filterAttempt])

  useEffect(() => {
    if (!propertyId) return
    const controller = new AbortController()
    Promise.all([
      loadAllPages(getProposals, controller.signal),
      loadAllPages(getConfirmedMatches, controller.signal, propertyId),
    ]).then(([proposals, candidates]) => {
      if (!controller.signal.aborted) setSelection({ propertyId, loading: false, error: '', items: proposals.filter((item) => item.listing_id === propertyId), candidates })
    }).catch((error) => {
      if (controller.signal.aborted) return
      if (error.status === 401) {
        expireSession().catch(() => setSelection({ propertyId, loading: false, error: 'Tu sesión ha caducado. Inicia sesión de nuevo.', items: [], candidates: [] }))
      } else {
        setSelection({ propertyId, loading: false, error: 'No se pudieron cargar las propuestas. Inténtalo de nuevo.', items: [], candidates: [] })
      }
    })
    return () => controller.abort()
  }, [expireSession, propertyId, selectionVersion])

  const currentSelection = selection.loading || selection.propertyId !== propertyId
    ? { ...selection, loading: true, error: '', items: [], candidates: [] }
    : selection
  const pendingProposal = currentSelection.items.find((item) => item.status === 'PENDING')
  const acceptedProposal = currentSelection.items.find((item) => item.status === 'ACCEPTED')
  const canPropose = selectedProperty?.availability !== 'CLOSED' && !pendingProposal && !acceptedProposal

  function refreshSelection() {
    setSelection((previous) => ({ ...previous, loading: true }))
    setSelectionVersion((version) => version + 1)
  }

  async function submitProposal(item) {
    if (decisionLock.current || currentSelection.loading || currentSelection.error || !canPropose) return
    const buyer = item.buyer?.name || 'este comprador'
    if (!window.confirm(`¿Proponer a ${buyer} para ${selectedProperty.title}?`)) return
    decisionLock.current = true
    setDecisionState({ saving: true, message: 'Enviando propuesta…' })
    const key = `${propertyId}:${item.id}`
    if (!requestIds.current.has(key)) requestIds.current.set(key, crypto.randomUUID())
    try {
      const { ok, status, data } = await createProposal(propertyId, item.id, requestIds.current.get(key))
      if (status === 401) {
        await expireSession()
        return
      }
      if (status === 409) {
        setDecisionState({ saving: false, message: 'La situación de la vivienda ha cambiado. Actualizando los datos.' })
        refreshSelection()
        refreshLists()
        setFilterAttempt((attempt) => attempt + 1)
        return
      }
      if (!ok || data?.listing_id !== propertyId || data?.match_id !== item.id || !data?.id) throw new Error()
      requestIds.current.delete(key)
      setDecisionState({ saving: false, message: 'Propuesta enviada.' })
      refreshSelection()
    } catch {
      setDecisionState({ saving: false, message: 'No se pudo confirmar el envío. Vuelve a intentarlo para comprobar el resultado.' })
    } finally {
      decisionLock.current = false
    }
  }

  async function cancelProposal(proposal) {
    if (decisionLock.current || proposal.status !== 'PENDING') return
    const buyer = currentSelection.candidates.find((item) => item.id === proposal.match_id)?.buyer?.name || 'el comprador'
    if (!window.confirm(`¿Cancelar la propuesta a ${buyer} para ${selectedProperty.title}?`)) return
    decisionLock.current = true
    setDecisionState({ saving: true, message: 'Cancelando propuesta…' })
    try {
      const { ok, status, data } = await resolveProposal(proposal.id, 'cancelar')
      if (status === 401) {
        await expireSession()
        return
      }
      if (status === 409) {
        setDecisionState({ saving: false, message: 'La propuesta ya ha cambiado. Actualizando los datos.' })
        refreshSelection()
        refreshLists()
        setFilterAttempt((attempt) => attempt + 1)
        return
      }
      if (!ok || data?.id !== proposal.id || data?.status !== 'CANCELLED') throw new Error()
      setDecisionState({ saving: false, message: 'Propuesta cancelada.' })
      refreshSelection()
      refreshLists()
    } catch {
      setDecisionState({ saving: false, message: 'No se pudo confirmar la cancelación. Vuelve a intentarlo.' })
    } finally {
      decisionLock.current = false
    }
  }

  function changeProperty(step) {
    if (decisionLock.current) return
    setPropertyIndex((index) => Math.max(0, Math.min(index + step, properties.length - 1)))
    setDecisionState({ saving: false, message: '' })
  }

  function refreshLists() {
    setPendingVersion((version) => version + 1)
    setConfirmedVersion((version) => version + 1)
    refreshSelection()
    setFilterAttempt((attempt) => attempt + 1)
  }

  function handlePointerDown(event) {
    if (decisionLock.current || pointer.current || !event.isPrimary || event.button !== 0 ||
        event.target.closest('button, a, input, select, textarea')) return
    pointer.current = { id: event.pointerId, x: event.clientX, y: event.clientY }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function handlePointerMove(event) {
    const start = pointer.current
    if (start?.id !== event.pointerId) return
    const dx = event.clientX - start.x
    const dy = event.clientY - start.y
    if (!start.horizontal) {
      if (Math.abs(dy) > 10 && Math.abs(dy) >= Math.abs(dx)) {
        pointer.current = null
        return
      }
      if (Math.abs(dx) < 10) return
      start.horizontal = true
      setDragging(true)
    }
    setDragOffset(Math.max(-120, Math.min(120, dx)))
  }

  function finishPointer(event, cancelled = false) {
    const start = pointer.current
    if (start?.id !== event.pointerId) return
    pointer.current = null
    setDragging(false)
    setDragOffset(0)
    const dx = event.clientX - start.x
    const dy = event.clientY - start.y
    if (!cancelled && start.horizontal && Math.abs(dx) >= 72 && Math.abs(dx) > Math.abs(dy)) {
      changeProperty(dx < 0 ? 1 : -1)
    }
  }

  async function saveDecision(matchId, decision) {
    if (decisionLock.current) return false
    decisionLock.current = true
    setDecisionState({ saving: true, message: 'Guardando decisión…' })
    try {
      const { ok, status, data } = await decideCandidate(matchId, decision)
      const confirmed = decision === 'LIKE'
      if (status === 401) {
        await expireSession()
        return 'expired'
      }
      if (status === 409) {
        refreshLists()
        setDecisionState({ saving: false, message: 'Esta candidatura ya tiene una decisión diferente. Hemos actualizado las listas.' })
        return 'conflict'
      }
      if (!ok || data?.id !== matchId || data?.status !== (confirmed ? 'CONFIRMED' : 'REJECTED')) {
        throw new Error(data?.error || 'El servidor no pudo guardar la decisión.')
      }
      if (confirmed) {
        setConfirmedVersion((version) => version + 1)
        refreshSelection()
      }
      setDecisionState({ saving: false, message: confirmed ? 'Match confirmado.' : 'Candidatura rechazada.' })
      return 'saved'
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
      </header>
      <div className="seller-dashboard__content seller-matches">
        <Link className="btn btn--ghost notifications-page__back" to="/vendedor/inicio">
          <span aria-hidden="true">&larr;</span> Volver al inicio
        </Link>
        <h1 className="home-page__title">Candidatos y matches</h1>
        {filterError && (
          <div className="seller-dashboard__message seller-dashboard__message--error" role="alert">
            <p>{filterError}</p>
            <button type="button" className="btn btn--ghost" onClick={() => {
              setFilterError('')
              setFilterAttempt((attempt) => attempt + 1)
            }}>Reintentar</button>
          </div>
        )}
        {!properties && !filterError && <p className="seller-dashboard__message" role="status">Cargando viviendas…</p>}
        {properties?.length === 0 && <p className="seller-dashboard__message">Todavía no tienes viviendas publicadas.</p>}
        {selectedProperty && (
          <div className="seller-matches__layout">
            <section className="seller-matches__property" aria-label="Vivienda seleccionada">
              <div className="seller-matches__property-header">
                <h2>Mis viviendas</h2>
                <span aria-live="polite">{currentIndex + 1} de {properties.length}</span>
              </div>
              <article className={`property-card seller-matches__property-card${dragging ? ' seller-matches__property-card--dragging' : ''}`}
                style={{ '--swipe-offset': `${dragOffset}px`, '--swipe-angle': `${dragOffset / 18}deg` }}
                tabIndex={0} aria-label={`Vivienda: ${selectedProperty.title}`}
                onPointerDown={handlePointerDown} onPointerMove={handlePointerMove}
                onPointerUp={finishPointer} onPointerCancel={(event) => finishPointer(event, true)}
                onLostPointerCapture={(event) => finishPointer(event, true)}
                onDragStart={(event) => event.preventDefault()}
                onKeyDown={(event) => {
                  if (event.repeat || event.target.closest('button, a, input, select, textarea')) return
                  if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
                    event.preventDefault()
                    changeProperty(event.key === 'ArrowRight' ? 1 : -1)
                  }
                }}>
                <PropertyGallery key={propertyId} property={selectedProperty} />
                <div className="property-card__body">
                  <h3>{selectedProperty.title}</h3>
                  <PropertyDetails property={selectedProperty} monthly />
                </div>
              </article>
              <div className="seller-matches__property-navigation">
                <button type="button" className="btn btn--ghost" onClick={() => changeProperty(-1)} disabled={currentIndex === 0 || decisionState.saving} aria-label="Vivienda anterior" title="Vivienda anterior">←</button>
                <button type="button" className="btn btn--ghost" onClick={() => changeProperty(1)} disabled={currentIndex === properties.length - 1 || decisionState.saving} aria-label="Vivienda siguiente" title="Vivienda siguiente">→</button>
              </div>
            </section>
            <div className="seller-matches__results">
              <div className="seller-dashboard__section-header">
                <h2>Candidaturas</h2>
                <button type="button" className="btn btn--ghost" disabled={decisionState.saving} onClick={refreshLists}>Actualizar</button>
              </div>
              <p className="seller-matches__feedback" role="status">{decisionState.message}</p>
              <div className="seller-matches__sections">
                <MatchSection key={`pending:${propertyId}:${pendingVersion}`} pending propertyId={propertyId} saving={decisionState.saving} onDecision={saveDecision} expireSession={expireSession} />
                <MatchSection key={`confirmed:${propertyId}:${confirmedVersion}`} propertyId={propertyId} expireSession={expireSession}
                  saving={decisionState.saving} selection={{ ...currentSelection, canPropose }} onPropose={submitProposal} />
                <section className="seller-matches__section" aria-labelledby="selection-title">
                  <h2 id="selection-title">Selección de inquilino</h2>
                  {currentSelection.loading && <p className="seller-dashboard__message" role="status">Cargando propuestas…</p>}
                  {currentSelection.error && (
                    <div className="seller-dashboard__message seller-dashboard__message--error" role="alert">
                      <p>{currentSelection.error}</p>
                      <button type="button" className="btn btn--ghost" onClick={refreshSelection}>Reintentar</button>
                    </div>
                  )}
                  {!currentSelection.loading && !currentSelection.error && (
                    <>
                      {(selectedProperty.availability === 'CLOSED' || acceptedProposal) && <p className="seller-dashboard__message">Anuncio cerrado.</p>}
                      {!currentSelection.items.length && <p className="seller-dashboard__message">No hay propuestas para esta vivienda.</p>}
                      {currentSelection.candidates.length === 0 && selectedProperty.availability !== 'CLOSED' && !acceptedProposal && (
                        <p className="seller-dashboard__message">No hay candidatos confirmados para seleccionar.</p>
                      )}
                      {currentSelection.items.length > 0 && (
                        <ul className="seller-dashboard__notifications-list" role="list">
                          {currentSelection.items.map((proposal) => {
                            const buyer = currentSelection.candidates.find((item) => item.id === proposal.match_id)?.buyer?.name || 'Comprador no disponible'
                            const date = proposal.created_at && new Date(proposal.created_at)
                            return (
                              <li className="seller-dashboard__notification seller-matches__item" key={proposal.id}>
                                <div className="seller-matches__summary">
                                  <h3>{buyer}</h3>
                                  <p>{proposalLabels[proposal.status] || proposal.status}</p>
                                  {date && !Number.isNaN(date.getTime()) && <p className="seller-matches__date">Propuesta: <time dateTime={proposal.created_at}>{dateFormat.format(date)}</time></p>}
                                </div>
                                {proposal.status === 'PENDING' && <button type="button" className="btn btn--ghost" disabled={decisionState.saving}
                                  aria-label={`Cancelar propuesta: ${buyer}, ${selectedProperty.title}`} onClick={() => cancelProposal(proposal)}>Cancelar propuesta</button>}
                              </li>
                            )
                          })}
                        </ul>
                      )}
                    </>
                  )}
                </section>
              </div>
            </div>
          </div>
        )}
      </div>
    </main>
  )
}