import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { getProposal, getProposals, resolveProposal } from '../api/properties'
import { Logo } from '../components/Logo'
import { PropertyDetails, PropertyGallery, PropertyPrice } from '../components/PropertyDetails'
import { useAuth } from '../hooks/useAuth'

const dateFormat = new Intl.DateTimeFormat('es-ES', { dateStyle: 'medium' })
const statusLabels = { PENDING: 'Pendiente', ACCEPTED: 'Aceptada', REJECTED: 'Rechazada', CANCELLED: 'Cancelada' }

function ProposalCard({ proposal, expireSession, refreshEpoch }) {
  const [detail, setDetail] = useState(null)
  const [detailError, setDetailError] = useState('')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [version, setVersion] = useState(0)
  const [loadedEpoch, setLoadedEpoch] = useState(null)
  const lock = useRef(false)
  const detailsId = useId()

  useEffect(() => {
    const controller = new AbortController()
    getProposal(proposal.id, controller.signal).then(({ ok, status, data }) => {
      if (controller.signal.aborted) return
      if (status === 401) {
        expireSession().catch(() => setDetailError('Tu sesión ha caducado. Inicia sesión de nuevo.'))
        return
      }
      if (!ok || !data?.listing || data.id !== proposal.id) throw new Error()
      setDetail(data)
      setLoadedEpoch(refreshEpoch)
      setDetailError('')
      setLoading(false)
    }).catch(() => {
      if (!controller.signal.aborted) {
        setDetailError('No se pudo cargar esta propuesta. Inténtalo de nuevo.')
        setLoading(false)
      }
    })
    return () => controller.abort()
  }, [expireSession, proposal.id, refreshEpoch, version])

  function refreshDetail() {
    setLoading(true)
    setDetailError('')
    setVersion((previous) => previous + 1)
  }

  async function respond(action) {
    if (lock.current || detail?.status !== 'PENDING') return
    const accepting = action === 'aceptar'
    if (!window.confirm(`¿${accepting ? 'Aceptar' : 'Rechazar'} la propuesta para ${detail.listing.title}?`)) return
    lock.current = true
    setBusy(true)
    setMessage('')
    try {
      const { ok, status, data } = await resolveProposal(proposal.id, action)
      if (status === 401) {
        await expireSession()
        return
      }
      if (status === 409) {
        setMessage('La propuesta ha cambiado. Hemos actualizado su estado.')
        refreshDetail()
        return
      }
      if (!ok || data?.id !== proposal.id || data?.status !== (accepting ? 'ACCEPTED' : 'REJECTED')) throw new Error()
      setDetail((previous) => ({ ...previous, ...data }))
      setMessage(accepting ? 'Selección definitiva aceptada.' : 'La propuesta ha sido rechazada.')
      refreshDetail()
    } catch {
      setMessage('No se pudo confirmar la respuesta. Vuelve a intentarlo para comprobar el resultado.')
    } finally {
      setBusy(false)
      lock.current = false
    }
  }

  return (
    <article className="property-card buyer-matches__card buyer-proposals__card">
      {loading && !detail && <p className="property-explorer__message" role="status">Cargando propuesta…</p>}
      {detailError && (
        <div className="buyer-proposals__error" role="alert">
          <p>{detailError}</p>
          <button type="button" className="btn btn--ghost" onClick={refreshDetail}>Reintentar</button>
        </div>
      )}
      {detail && (
        <>
          <div className="buyer-matches__thumbnail">
            {detail.listing.photos?.[0] ? <img src={detail.listing.photos[0]} alt={detail.listing.title} loading="lazy" /> : <span>Sin foto</span>}
          </div>
          <div className="property-card__body buyer-matches__body">
            <h2>{detail.listing.title}</h2>
            <p className="property-card__location">{detail.listing.city} · <strong><PropertyPrice value={detail.listing.price} monthly /></strong></p>
            {(detail.status === 'ACCEPTED' || detail.listing.availability === 'CLOSED') && <p className="property-availability">Anuncio cerrado</p>}
            <dl className="buyer-matches__metadata">
              <div><dt>Vendedor</dt><dd>{detail.seller?.name || 'No disponible'}</dd></div>
              <div><dt>Recibida</dt><dd><time dateTime={detail.created_at}>{dateFormat.format(new Date(detail.created_at))}</time></dd></div>
              <div><dt>Estado</dt><dd>{statusLabels[detail.status] || detail.status}</dd></div>
            </dl>
            <div className="seller-matches__actions">
              <button type="button" className="btn btn--ghost uniform-action" aria-expanded={expanded} aria-controls={detailsId}
                onClick={() => setExpanded(!expanded)}>{expanded ? 'Ocultar vivienda' : 'Ver vivienda'}</button>
              {detail.status === 'PENDING' && (
                <>
                  <button type="button" className="btn btn--dark" disabled={busy || loading || loadedEpoch !== refreshEpoch || Boolean(detailError)} onClick={() => respond('aceptar')}>Aceptar</button>
                  <button type="button" className="btn btn--ghost" disabled={busy || loading || loadedEpoch !== refreshEpoch || Boolean(detailError)} onClick={() => respond('rechazar')}>Rechazar</button>
                </>
              )}
            </div>
            {message && <p className="buyer-proposals__message" role="status">{message}</p>}
          </div>
          <div className="buyer-matches__details" id={detailsId} hidden={!expanded}>
            {expanded && <><PropertyGallery property={detail.listing} /><PropertyDetails property={detail.listing} showPrice={false} /></>}
          </div>
        </>
      )}
    </article>
  )
}

export function BuyerProposalsPage() {
  const { expireSession } = useAuth()
  const [items, setItems] = useState([])
  const [cursor, setCursor] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshEpoch, setRefreshEpoch] = useState(0)
  const request = useRef(null)

  const load = useCallback((nextCursor = null) => {
    if (request.current) return
    const controller = new AbortController()
    request.current = controller
    getProposals(nextCursor, controller.signal).then(({ ok, status, data }) => {
      if (controller.signal.aborted) return
      if (status === 401) {
        expireSession().catch(() => setError('Tu sesión ha caducado. Inicia sesión de nuevo.'))
        return
      }
      if (!ok || !Array.isArray(data?.items)) throw new Error()
      setItems((previous) => nextCursor ? [...previous, ...data.items] : data.items)
      if (!nextCursor) setRefreshEpoch((previous) => previous + 1)
      setCursor(data.next_cursor || null)
    }).catch(() => {
      if (!controller.signal.aborted) setError('No se pudieron cargar las propuestas. Inténtalo de nuevo.')
    }).finally(() => {
      if (request.current === controller) {
        request.current = null
        setLoading(false)
      }
    })
  }, [expireSession])

  useEffect(() => {
    load()
    return () => {
      request.current?.abort()
      request.current = null
    }
  }, [load])

  function reload(nextCursor = null) {
    setLoading(true)
    setError('')
    load(nextCursor)
  }

  return (
    <main className="home-page home-page--buyer">
      <header className="home-page__header"><Logo size="sm" to="/comprador/inicio" /></header>
      <div className="home-page__content buyer-matches">
        <Link className="btn btn--ghost notifications-page__back" to="/comprador/matches"><span aria-hidden="true">&larr;</span> Volver a mis matches</Link>
        <div className="buyer-matches__heading">
          <h1 className="home-page__title">Propuestas recibidas</h1>
          <button type="button" className="btn btn--ghost" disabled={loading} onClick={() => reload()}>Actualizar</button>
        </div>
        {items.length > 0 && <ul className="buyer-matches__list" role="list">{items.map((item) => <li key={item.id}><ProposalCard proposal={item} expireSession={expireSession} refreshEpoch={refreshEpoch} /></li>)}</ul>}
        {loading && <p className="property-explorer__message" role="status">Cargando propuestas…</p>}
        {error && <div className="property-explorer__message property-explorer__message--error" role="alert"><p>{error}</p><button type="button" className="btn btn--ghost" onClick={() => reload(cursor)}>Reintentar</button></div>}
        {!loading && !error && !items.length && !cursor && <p className="property-explorer__message">Todavía no tienes propuestas recibidas.</p>}
        {cursor && !loading && !error && <button type="button" className="btn btn--ghost" onClick={() => reload(cursor)}>Cargar más</button>}
      </div>
    </main>
  )
}