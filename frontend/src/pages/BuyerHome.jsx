import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { decideProperty, exploreProperties } from '../api/properties'
import { Logo } from '../components/Logo'
import { PropertyDetails, PropertyGallery } from '../components/PropertyDetails'
import { SearchPreferencesForm } from '../components/SearchPreferencesForm'
import { useAuth } from '../hooks/useAuth'

const SWIPE_THRESHOLD = 72
const INTERACTIVE = 'button, a, input, select, textarea'

function IconHeart() {
  return (
    <svg className="icon-heart" viewBox="0 0 24 22" fill="currentColor" aria-hidden="true">
      <path d="M12 21C9.8 18.9 2 13.7 2 7.2C2 3.8 4.8 1 8.2 1C10.1 1 11.6 2 12 3.2C12.4 2 13.9 1 15.8 1C19.2 1 22 3.8 22 7.2C22 13.7 14.2 18.9 12 21Z" />
    </svg>
  )
}

export function BuyerHome() {
  const { logout } = useAuth()
  const navigate = useNavigate()
  const [properties, setProperties] = useState([])
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState('')
  const [decisionError, setDecisionError] = useState('')
  const [retryDecision, setRetryDecision] = useState(null)
  const [decisionBusy, setDecisionBusy] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [offset, setOffset] = useState(0)
  const [dragging, setDragging] = useState(false)
  const [preferencesOpen, setPreferencesOpen] = useState(false)
  const pointer = useRef(null)
  const decisionLock = useRef(false)
  const loadingLock = useRef(false)
  const nextCursor = useRef(null)

  const property = properties[0]

  const loadProperties = useCallback(async (reset = false, showLoading = true) => {
    if (loadingLock.current) return
    loadingLock.current = true
    if (reset) nextCursor.current = null
    if (showLoading) {
      setStatus('loading')
      setError('')
    }
    try {
      const result = await exploreProperties(reset ? null : nextCursor.current)
      if (!result.ok) {
        setError(result.data?.error || 'No se pudieron cargar las viviendas.')
        setStatus('error')
        return
      }
      const items = result.data.items || []
      setProperties((current) => reset ? items : [...current, ...items])
      nextCursor.current = result.data.next_cursor || null
      setStatus('ready')
    } catch {
      setError('No hay conexión con el servidor. Inténtalo de nuevo.')
      setStatus('error')
    } finally {
      loadingLock.current = false
    }
  }, [])

  useEffect(() => {
    const task = window.setTimeout(() => loadProperties(true, false), 0)
    return () => window.clearTimeout(task)
  }, [loadProperties])

  async function handleDecision(decision = retryDecision) {
    if (!property || !decision || decisionLock.current) return
    decisionLock.current = true
    pointer.current = null
    setDragging(false)
    setOffset(decision === 'LIKE' ? 100 : -100)
    setDecisionBusy(true)
    setDecisionError('')
    try {
      const result = await decideProperty(property.id, decision)
      const confirmedDecision = result.data?.decision
      const validConfirmation =
        confirmedDecision?.listing_id === property.id &&
        confirmedDecision?.value === decision &&
        (decision === 'LIKE'
          ? result.data?.match?.listing_id === property.id && Boolean(result.data.match.id)
          : result.data?.match === null)
      if (result.ok && validConfirmation) {
        const remaining = properties.slice(1)
        setProperties(remaining)
        setRetryDecision(null)
        setFeedback(
          decision === 'LIKE'
            ? 'Interés enviado'
            : 'Vivienda descartada. Tu decisión se ha guardado.',
        )
        if (remaining.length === 0 && nextCursor.current) await loadProperties()
      } else if (result.ok) {
        setDecisionError('El servidor no confirmó la decisión. Inténtalo de nuevo.')
        setRetryDecision(decision)
      } else if (result.status === 409) {
        setDecisionError('Esta vivienda ya tenía una decisión. Actualizando el explorador…')
        setRetryDecision(null)
        await loadProperties(true)
      } else if (result.status === 401) {
        setDecisionError('Tu sesión ha caducado. Inicia sesión de nuevo.')
        await logout()
      } else {
        setDecisionError(result.data?.error || 'No se pudo guardar la decisión. Inténtalo de nuevo.')
        setRetryDecision(decision)
      }
    } catch {
      setDecisionError('No hay conexión para guardar la decisión. Comprueba tu conexión e inténtalo de nuevo.')
      setRetryDecision(decision)
    } finally {
      decisionLock.current = false
      setDecisionBusy(false)
      setOffset(0)
    }
  }

  function handlePointerDown(event) {
    if (decisionLock.current || pointer.current || !event.isPrimary || event.button !== 0 ||
        event.target.closest(INTERACTIVE)) return
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
        cancelSwipe(event)
        return
      }
      if (Math.abs(dx) < 10) return
      start.horizontal = true
      setDragging(true)
    }
    setOffset(Math.max(-160, Math.min(160, dx)))
  }

  function cancelSwipe(event) {
    if (pointer.current?.id !== event.pointerId) return
    pointer.current = null
    setDragging(false)
    setOffset(0)
  }

  function handlePointerUp(event) {
    const start = pointer.current
    if (start?.id !== event.pointerId) return
    const dx = event.clientX - start.x
    const dy = event.clientY - start.y
    if (start.horizontal && Math.abs(dx) >= SWIPE_THRESHOLD && Math.abs(dx) > Math.abs(dy)) {
      handleDecision(dx > 0 ? 'LIKE' : 'PASS')
    } else {
      cancelSwipe(event)
    }
  }

  function handleKeyDown(event) {
    if (event.repeat || (event.target !== event.currentTarget && event.target.closest(INTERACTIVE))) return
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault()
      handleDecision(event.key === 'ArrowRight' ? 'LIKE' : 'PASS')
    }
  }

  return (
    <main className="home-page home-page--buyer">
      <header className="home-page__header buyer-explorer__header">
        <Logo size="sm" to="/comprador/inicio" />
        <div className="buyer-dashboard__account">
          <span className="buyer-dashboard__role uniform-action">Comprador</span>
          <button type="button" className="uniform-action" onClick={() => navigate('/comprador/matches')}>
            Mis matches
          </button>
          <button type="button" className="uniform-action" onClick={() => navigate('/notificaciones')}>
            Notificaciones
          </button>
          <button type="button" className="home-page__profile uniform-action" onClick={() => navigate('/mi-perfil')}>
            Mi perfil
          </button>
          <button type="button" className="buyer-dashboard__logout uniform-action" onClick={logout}>
            Cerrar sesión
          </button>
        </div>
      </header>
      <div className="home-page__content buyer-explorer">
        <div className="buyer-filter-bar">
          <button type="button" className="buyer-filter-bar__button" onClick={() => setPreferencesOpen(true)}>
            Filtros
          </button>
        </div>
        {status === 'loading' && <p className="property-explorer__message">Cargando viviendas…</p>}
        {status === 'error' && (
          <div className="property-explorer__message property-explorer__message--error" role="alert">
            <p>{error}</p>
            <button type="button" className="btn btn--ghost" onClick={() => loadProperties(true)}>Reintentar</button>
          </div>
        )}
        {status === 'ready' && !property && (
          <div className="property-explorer__message">
            <p>{'No hay más viviendas por explorar.'}</p>
            <button type="button" className="btn btn--ghost" onClick={() => loadProperties(true)}>Actualizar</button>
          </div>
        )}
        {feedback && <p className="property-card__feedback" role="status">{feedback}</p>}
        {status === 'ready' && property && (
          <div className="buyer-swipe-deck">
            <article
              className={`property-card buyer-swipe-card${dragging ? ' buyer-swipe-card--dragging' : ''}`}
              style={{ '--swipe-offset': `${offset}px`, '--swipe-angle': `${offset / 14}deg` }}
              tabIndex={0}
              aria-label="Vivienda. Usa las flechas izquierda y derecha para descartar o mostrar interés."
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onPointerCancel={cancelSwipe}
              onLostPointerCapture={cancelSwipe}
              onDragStart={(event) => event.preventDefault()}
              onKeyDown={handleKeyDown}
            >
              <PropertyGallery key={property.id} property={property} />
              {Math.abs(offset) > 20 && (
                <span className={`buyer-swipe-card__stamp buyer-swipe-card__stamp--${offset > 0 ? 'like' : 'pass'}`}
                  aria-hidden="true" style={{ opacity: Math.min(Math.abs(offset) / SWIPE_THRESHOLD, 1) }}>
                  {offset > 0 ? 'Me interesa' : 'Paso'}
                </span>
              )}
              <div className="property-card__body">
                {decisionError && (
                  <div className="property-card__error" role="alert">
                    <p>{decisionError}</p>
                    {retryDecision && (
                      <button type="button" className="btn btn--ghost" onClick={() => handleDecision(retryDecision)}
                        disabled={decisionBusy}>Reintentar</button>
                    )}
                  </div>
                )}
                <h2>{property.title}</h2>
                <div className="property-card__actions">
                  <button type="button" className="swipe-btn swipe-btn--pass" onClick={() => handleDecision('PASS')}
                    disabled={decisionBusy} aria-label="No me interesa" title="No me interesa">✕</button>
                  <button type="button" className="swipe-btn swipe-btn--like" onClick={() => handleDecision('LIKE')}
                    disabled={decisionBusy} aria-label="Me interesa" title="Me interesa"><IconHeart /></button>
                </div>
                <PropertyDetails property={property} />
              </div>
            </article>
          </div>
        )}
      </div>
      {preferencesOpen && (
        <div className="preferences-modal" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setPreferencesOpen(false)
        }}>
          <SearchPreferencesForm
            inModal
            onCancel={() => setPreferencesOpen(false)}
            onSaved={() => {
              setPreferencesOpen(false)
              loadProperties(true)
            }}
            onReset={() => loadProperties(true)}
          />
        </div>
      )}
    </main>
  )
}
