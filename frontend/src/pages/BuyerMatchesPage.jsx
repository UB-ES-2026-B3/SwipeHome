import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { getConfirmedMatches } from '../api/properties'
import { Logo } from '../components/Logo'
import { PropertyDetails, PropertyPrice } from '../components/PropertyDetails'
import { useAuth } from '../hooks/useAuth'

const confirmationDate = new Intl.DateTimeFormat('es-ES', { dateStyle: 'medium' })

function MatchCard({ match }) {
  const [expanded, setExpanded] = useState(false)
  const detailsId = useId()
  const property = match.listing
  const hasDetails = property.price != null

  return (
    <article className="property-card buyer-matches__card">
      <div className="buyer-matches__thumbnail">
        {property.photos?.[0] ? (
          <img src={property.photos[0]} alt={property.title || 'Vivienda'} loading="lazy" />
        ) : <span>Sin foto</span>}
      </div>
      <div className="property-card__body buyer-matches__body">
        <h2>{property.title || 'Vivienda no disponible'}</h2>
        {hasDetails ? (
          <p className="property-card__location">
            {property.city} · <strong><PropertyPrice value={property.price} monthly /></strong>
          </p>
        ) : <p className="property-card__location">Ficha no disponible</p>}
        <dl className="buyer-matches__metadata">
          <div><dt>Vendedor</dt><dd>{match.seller?.name || 'No disponible'}</dd></div>
          <div><dt>Confirmado el</dt><dd>
            <time dateTime={match.confirmed_at}>{confirmationDate.format(new Date(match.confirmed_at))}</time>
          </dd></div>
        </dl>
        {hasDetails && (
          <button type="button" className="btn btn--ghost uniform-action" aria-expanded={expanded}
            aria-controls={detailsId} onClick={() => setExpanded(!expanded)}>
            {expanded ? 'Ocultar información' : 'Ver información'}
          </button>
        )}
      </div>
      {hasDetails && (
        <div className="buyer-matches__details" id={detailsId} hidden={!expanded}>
          {expanded && <PropertyDetails property={property} showPrice={false} />}
        </div>
      )}
    </article>
  )
}

export function BuyerMatchesPage() {
  const { expireSession } = useAuth()
  const [matches, setMatches] = useState([])
  const [nextCursor, setNextCursor] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const request = useRef(null)

  const loadMatches = useCallback((cursor) => {
    if (request.current) return
    const controller = new AbortController()
    request.current = controller
    getConfirmedMatches(cursor, controller.signal)
      .then(({ ok, status, data }) => {
        if (controller.signal.aborted) return
        if (status === 401) {
          expireSession().catch(() => setError('Tu sesión ha caducado. Inicia sesión de nuevo.'))
          return
        }
        if (!ok || !Array.isArray(data?.items)) {
          setError('No se pudieron cargar los matches confirmados.')
          return
        }
        const confirmed = data.items.filter((match) => match.status === 'CONFIRMED')
        setMatches((current) => cursor ? [...current, ...confirmed] : confirmed)
        setNextCursor(data.next_cursor ?? null)
      })
      .catch(() => {
        if (!controller.signal.aborted) setError('No hay conexión con el servidor.')
      })
      .finally(() => {
        if (request.current === controller) {
          request.current = null
          setLoading(false)
        }
      })
  }, [expireSession])

  function loadMore() {
    setLoading(true)
    setError('')
    loadMatches(nextCursor)
  }

  function refreshMatches() {
    setLoading(true)
    setError('')
    loadMatches(null)
  }

  useEffect(() => {
    loadMatches(null)
    return () => {
      request.current?.abort()
      request.current = null
    }
  }, [loadMatches])

  return (
    <main className="home-page home-page--buyer">
      <header className="home-page__header">
        <Logo size="sm" to="/comprador/inicio" />
      </header>
      <div className="home-page__content buyer-matches">
        <Link className="btn btn--ghost notifications-page__back" to="/comprador/inicio">
          <span aria-hidden="true">&larr;</span> Volver al inicio
        </Link>
        <div className="buyer-matches__heading">
          <h1 className="home-page__title">Mis matches</h1>
          <button type="button" className="btn btn--ghost" disabled={loading} onClick={refreshMatches}>Actualizar</button>
        </div>
        {matches.length > 0 && (
          <ul className="buyer-matches__list" role="list">
            {matches.map((match) => <li key={match.id}><MatchCard match={match} /></li>)}
          </ul>
        )}
        {loading && <p className="property-explorer__message" role="status">Cargando matches…</p>}
        {error && (
          <div className="property-explorer__message property-explorer__message--error">
            <p role="alert">{error}</p>
            <button type="button" className="btn btn--ghost" onClick={loadMore}>Reintentar</button>
          </div>
        )}
        {!loading && !error && matches.length === 0 && !nextCursor && (
          <p className="property-explorer__message">Todavía no tienes matches confirmados.</p>
        )}
        {nextCursor && !error && (
          <button type="button" className="btn btn--ghost" disabled={loading} onClick={loadMore}>
            Cargar más
          </button>
        )}
      </div>
    </main>
  )
}