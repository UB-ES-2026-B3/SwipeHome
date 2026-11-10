import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { decideProperty, exploreProperties } from '../api/properties'
import { Logo } from '../components/Logo'
import { useAuth } from '../hooks/useAuth'

export function BuyerHome() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [properties, setProperties] = useState([])
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState('')
  const [decisionError, setDecisionError] = useState('')
  const [retryDecision, setRetryDecision] = useState(null)
  const [decisionBusy, setDecisionBusy] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [gallery, setGallery] = useState({ propertyId: null, index: 0 })
  const pointerStart = useRef(null)
  const decisionLock = useRef(false)
  const loadingLock = useRef(false)
  const nextCursor = useRef(null)

  const property = properties[0]
  const photos = property?.photos || []
  const galleryIndex = gallery.propertyId === property?.id ? gallery.index : 0

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
    loadProperties(true, false)
  }, [loadProperties])

  async function handleDecision(decision = retryDecision) {
    if (!property || !decision || decisionLock.current) return
    decisionLock.current = true
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
            ? '¡Match creado! El vendedor ha recibido tu interés.'
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
    }
  }

  function handlePointerDown(event) {
    if (decisionBusy || event.target.closest('button, a, input, select, textarea')) return
    pointerStart.current = { x: event.clientX, y: event.clientY }
  }

  function handlePointerUp(event) {
    const start = pointerStart.current
    pointerStart.current = null
    if (!start || decisionBusy || event.target.closest('button, a, input, select, textarea')) return
    const dx = event.clientX - start.x
    const dy = event.clientY - start.y
    if (Math.abs(dx) < 60 || Math.abs(dx) <= Math.abs(dy)) return
    handleDecision(dx > 0 ? 'LIKE' : 'PASS')
  }

  function handleKeyDown(event) {
    if (event.target !== event.currentTarget && event.target.closest('button, a, input, select, textarea')) return
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault()
      handleDecision(event.key === 'ArrowRight' ? 'LIKE' : 'PASS')
    }
  }

  function changePhoto(step) {
    setGallery((current) => {
      const index = current.propertyId === property.id ? current.index : 0
      return {
        propertyId: property.id,
        index: Math.min(Math.max(index + step, 0), photos.length - 1),
      }
    })
  }

  function formatPrice(value) {
    const amount = Number(value)
    return Number.isFinite(amount)
      ? amount.toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      : value
  }

  return (
    <main className="home-page home-page--buyer">
      <header className="home-page__header">
        <Logo size="sm" to="/comprador/inicio" />
        <div className="buyer-dashboard__account">
          <span className="buyer-dashboard__role uniform-action">Comprador</span>
          <button type="button" className="uniform-action" onClick={() => navigate('/notificaciones')}>
            Notificaciones
          </button>
          <button type="button" className="home-page__profile uniform-action" onClick={() => navigate('/mi-perfil')}>
            Mi perfil
          </button>
          <button type="button" className="buyer-dashboard__logout uniform-action" onClick={logout}>
            LogOut
          </button>
        </div>
      </header>
      <div className="home-page__content">
        <h1 className="home-page__title">¡Bienvenido, {user?.name || 'Comprador'}!</h1>
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
          <article
            className="property-card"
            tabIndex={0}
            aria-label="Vivienda. Usa las flechas izquierda y derecha para descartar o mostrar interés."
            onPointerDown={handlePointerDown}
            onPointerUp={handlePointerUp}
            onKeyDown={handleKeyDown}
          >
            <div className="property-card__gallery">
              {photos.length > 0 ? (
                <img src={photos[galleryIndex]} alt={`${property.title}, fotografía ${galleryIndex + 1}`} />
              ) : (
                <div className="property-card__no-photo">Sin fotografías</div>
              )}
              {photos.length > 1 && (
                <>
                  <button type="button" className="property-card__gallery-control property-card__gallery-control--prev"
                    onClick={() => changePhoto(-1)} disabled={galleryIndex === 0} aria-label="Fotografía anterior">‹</button>
                  <button type="button" className="property-card__gallery-control property-card__gallery-control--next"
                    onClick={() => changePhoto(1)} disabled={galleryIndex === photos.length - 1} aria-label="Fotografía siguiente">›</button>
                  <span className="property-card__counter">{galleryIndex + 1} de {photos.length}</span>
                </>
              )}
            </div>
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
              <p className="property-card__location">{property.street}, {property.postal_code} · {property.city}</p>
              <p className="property-card__description">{property.description}</p>
              <dl className="property-card__details">
                <div><dt>Precio</dt><dd>{formatPrice(property.price)} €</dd></div>
                <div><dt>Superficie</dt><dd>{property.surface} m²</dd></div>
                <div><dt>Dormitorios</dt><dd>{property.bedrooms}</dd></div>
                <div><dt>Baños</dt><dd>{property.bathrooms}</dd></div>
                <div><dt>Personas</dt><dd>{property.people}</dd></div>
                <div><dt>Compartido</dt><dd>{property.shared_accommodation ? 'Sí' : 'No'}</dd></div>
              </dl>
              <div className="property-card__actions">
                <button type="button" className="swipe-btn swipe-btn--pass" onClick={() => handleDecision('PASS')}
                  disabled={decisionBusy} aria-label="No me interesa">✕</button>
                <button type="button" className="swipe-btn swipe-btn--like" onClick={() => handleDecision('LIKE')}
                  disabled={decisionBusy} aria-label="Me interesa">♥</button>
              </div>
            </div>
          </article>
        )}
      </div>
    </main>
  )
}
