import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { decideProperty, exploreProperties } from '../api/properties'
import { Logo } from '../components/Logo'
import { useAuth } from '../hooks/useAuth'

export function BuyerHome() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [properties, setProperties] = useState([])
  const [nextOffset, setNextOffset] = useState(0)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState('')
  const [decisionBusy, setDecisionBusy] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [galleryIndex, setGalleryIndex] = useState(0)
  const pointerStart = useRef(null)

  const property = properties[0]
  const photos = property?.photos || []

  async function loadProperties(reset = false) {
    setStatus('loading')
    setError('')
    try {
      const result = await exploreProperties(reset ? 0 : nextOffset)
      if (!result.ok) {
        setError(result.data?.error || 'No se pudieron cargar las viviendas.')
        setStatus('error')
        return
      }
      const items = result.data.items || []
      setProperties((current) => reset ? items : [...current, ...items])
      setNextOffset(result.data.next_offset)
      setStatus('ready')
    } catch {
      setError('No hay conexión con el servidor. Inténtalo de nuevo.')
      setStatus('error')
    }
  }

  useEffect(() => {
    loadProperties(true)
  }, [])

  useEffect(() => {
    setGalleryIndex(0)
    setFeedback('')
  }, [property?.id])

  async function handleDecision(decision) {
    if (!property || decisionBusy) return
    setDecisionBusy(true)
    setFeedback('')
    try {
      const result = await decideProperty(property.id, decision)
      if (result.ok) {
        setProperties((current) => current.slice(1))
        if (result.data.match) setFeedback('Match creado')
        if (nextOffset !== null && properties.length <= 1) loadProperties()
      } else if (result.status === 409) {
        setError('Esta vivienda ya tenía una decisión. Actualizando el explorador…')
        await loadProperties(true)
      } else if (result.status === 401) {
        setError('Tu sesión ha caducado. Inicia sesión de nuevo.')
        await logout()
      } else {
        setError(result.data?.error || 'No se pudo guardar la decisión.')
      }
    } catch {
      setError('No se pudo guardar la decisión. Inténtalo de nuevo.')
    } finally {
      setDecisionBusy(false)
    }
  }

  function handlePointerDown(event) {
    if (!decisionBusy) pointerStart.current = { x: event.clientX, y: event.clientY }
  }

  function handlePointerUp(event) {
    const start = pointerStart.current
    pointerStart.current = null
    if (!start || decisionBusy) return
    const dx = event.clientX - start.x
    const dy = event.clientY - start.y
    if (Math.abs(dx) < 60 || Math.abs(dx) <= Math.abs(dy)) return
    handleDecision(dx > 0 ? 'LIKE' : 'PASS')
  }

  function changePhoto(step) {
    setGalleryIndex((index) => Math.min(Math.max(index + step, 0), photos.length - 1))
  }

  return (
    <main className="home-page home-page--buyer">
      <header className="home-page__header">
        <Logo size="sm" to="/comprador/inicio" />
        <button type="button" className="home-page__profile uniform-action" onClick={() => navigate('/mi-perfil')}>
          Mi perfil
        </button>
      </header>
      <div className="home-page__content">
        <h1 className="home-page__title">¡Bienvenido, {user?.name || 'Comprador'}!</h1>
        <p className="home-page__role-badge home-page__role-badge--buyer">Comprador</p>
        {status === 'loading' && <p className="property-explorer__message">Cargando viviendas…</p>}
        {status === 'error' && (
          <div className="property-explorer__message property-explorer__message--error" role="alert">
            <p>{error}</p>
            <button type="button" className="btn btn--ghost" onClick={() => loadProperties(true)}>Reintentar</button>
          </div>
        )}
        {status === 'ready' && !property && (
          <div className="property-explorer__message">
            <p>{error || 'No hay más viviendas por explorar.'}</p>
            <button type="button" className="btn btn--ghost" onClick={() => loadProperties(true)}>Actualizar</button>
          </div>
        )}
        {status === 'ready' && property && (
          <article
            className="property-card"
            onPointerDown={handlePointerDown}
            onPointerUp={handlePointerUp}
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
              {error && <p className="property-card__error" role="alert">{error}</p>}
              <h2>{property.title}</h2>
              <p className="property-card__location">{property.street}, {property.postal_code} · {property.city}</p>
              <p className="property-card__description">{property.description}</p>
              <dl className="property-card__details">
                <div><dt>Precio</dt><dd>{property.price.toLocaleString('es-ES', { minimumFractionDigits: 2 })} €</dd></div>
                <div><dt>Superficie</dt><dd>{property.surface} m²</dd></div>
                <div><dt>Dormitorios</dt><dd>{property.bedrooms}</dd></div>
                <div><dt>Baños</dt><dd>{property.bathrooms}</dd></div>
                <div><dt>Personas</dt><dd>{property.people}</dd></div>
                <div><dt>Compartido</dt><dd>{property.shared_accommodation ? 'Sí' : 'No'}</dd></div>
              </dl>
              {feedback && <p className="property-card__feedback" role="status">{feedback}</p>}
              <div className="property-card__actions">
                <button type="button" className="swipe-btn swipe-btn--pass" onClick={() => handleDecision('PASS')}
                  disabled={decisionBusy} aria-label="Descartar vivienda">✕</button>
                <button type="button" className="swipe-btn swipe-btn--like" onClick={() => handleDecision('LIKE')}
                  disabled={decisionBusy} aria-label="Mostrar interés en la vivienda">♥</button>
              </div>
            </div>
          </article>
        )}
        <button type="button" className="home-page__logout uniform-action" onClick={logout}>Cerrar sesión</button>
      </div>
    </main>
  )
}
