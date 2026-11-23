import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { getProposal, getProposals, respondToProposal } from '../api/properties'
import { Logo } from '../components/Logo'
import { useAuth } from '../hooks/useAuth'

const statuses = {
  PENDING: 'Pendiente',
  ACCEPTED: 'Aceptada',
  REJECTED: 'Rechazada',
  CANCELLED: 'Cancelada',
}

export function ProposalsPage() {
  const { selectionId } = useParams()
  return <ProposalsContent key={selectionId ?? 'list'} selectionId={selectionId} />
}

function ProposalsContent({ selectionId }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [query, setQuery] = useState({ cursor: null })
  const [response, setResponse] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [actionError, setActionError] = useState('')
  const inProgress = useRef(false)
  const loading = response?.query !== query
  const seller = user.role === 'SELLER'
  const data = response?.data
  const loadError = loading ? '' : response?.error

  useEffect(() => {
    let active = true

    async function load() {
      try {
        const result = selectionId ? await getProposal(selectionId) : await getProposals(query)
        if (!active) return
        if (result.status === 401 && await logout()) {
          if (active) navigate('/login', { replace: true })
          return
        }
        if (active) setResponse(result.ok
          ? { query, data: result.data }
          : { query, error: result.data?.error || 'No se pudieron consultar las propuestas.' })
      } catch {
        if (active) setResponse({ query, error: 'No hay conexión con el servidor. Inténtalo de nuevo.' })
      }
    }

    load()
    return () => { active = false }
  }, [selectionId, query, logout, navigate])

  async function respond(decision) {
    if (inProgress.current || loading || data?.status !== 'PENDING') return
    inProgress.current = true
    setSubmitting(true)
    setActionError('')
    try {
      const result = await respondToProposal(selectionId, decision)
      if (result.status === 401 && await logout()) {
        navigate('/login', { replace: true })
        return
      }
      if (!result.ok) {
        if (result.status === 409 || result.status === 404) {
          setActionError('La propuesta cambió. Comprueba su estado actualizado.')
          setQuery({ cursor: null })
        } else {
          setActionError(result.data?.error || 'No se pudo guardar la respuesta. Puedes reintentar.')
        }
        return
      }
      setResponse({
        query,
        data: {
          ...data,
          status: result.data.status,
          updated_at: result.data.updated_at,
          listing: {
            ...data.listing,
            available: result.data.status === 'ACCEPTED' ? false : data.listing.available,
          },
        },
      })
    } catch {
      setActionError('No hay conexión con el servidor. Puedes reintentar la respuesta.')
    } finally {
      inProgress.current = false
      setSubmitting(false)
    }
  }

  const home = seller ? '/vendedor/inicio' : '/comprador/inicio'
  return (
    <main className="matches-page">
      <header className="home-page__header">
        <Logo size="sm" to={home} />
        <nav className="matches-page__header-actions" aria-label="Cuenta">
          <Link className="uniform-action" to={home}>Volver al inicio</Link>
          <Link className="uniform-action" to="/mis-matches">Mis matches</Link>
          <Link className="uniform-action" to="/notificaciones">Notificaciones</Link>
          <button type="button" className="uniform-action" onClick={logout}>Salir</button>
        </nav>
      </header>
      <section className="matches-page__content" aria-labelledby="proposals-title">
        <div className="matches-page__heading">
          <div>
            {selectionId && <Link to="/propuestas">Todas las propuestas</Link>}
            <h1 id="proposals-title">{selectionId ? 'Detalle de la propuesta' : 'Propuestas'}</h1>
          </div>
          <button type="button" className="btn btn--ghost" disabled={loading || submitting}
            onClick={() => { setActionError(''); setQuery({ ...query }) }}>
            Actualizar
          </button>
        </div>
        {loading && <p role="status" className="matches-page__message">Cargando propuestas…</p>}
        {loadError && (
          <div className="matches-page__message matches-page__message--error">
            <p role="alert">{loadError}</p>
            <button type="button" className="btn btn--ghost" onClick={() => setQuery({ ...query })}>
              Reintentar
            </button>
          </div>
        )}
        {actionError && <p role="alert" className="matches-page__message matches-page__message--error">{actionError}</p>}
        {data && (selectionId
          ? <ProposalDetail proposal={data} seller={seller} disabled={loading || submitting}
              submitting={submitting} respond={respond} />
          : (
            <>
              {data.items.length === 0 && <p className="matches-page__message">Aún no tienes propuestas.</p>}
              <ul className="matches-page__list">
                {data.items.map((item) => (
                  <li className="matches-page__item" key={item.id}>
                    <Link to={`/propuestas/${item.id}`}>{item.listing.title} · {statuses[item.status]}</Link>
                  </li>
                ))}
              </ul>
              <div className="proposal-actions">
                {query.cursor && <button type="button" className="btn btn--ghost" disabled={loading}
                  onClick={() => setQuery({ cursor: null })}>Volver a las más recientes</button>}
                {data.next_cursor && <button type="button" className="btn btn--ghost" disabled={loading}
                  onClick={() => setQuery({ cursor: data.next_cursor })}>Siguiente página</button>}
              </div>
            </>
          ))}
      </section>
    </main>
  )
}

function ProposalDetail({ proposal, seller, disabled, submitting, respond }) {
  const { listing } = proposal
  return (
    <article className="matches-page__item proposal-detail">
      <h2>{listing.title}</h2>
      <p role="status">Estado: {statuses[proposal.status]}</p>
      {listing.available === false && <p>Vivienda no disponible</p>}
      <p>{listing.street}, {listing.postal_code} {listing.city}</p>
      <p>{listing.description}</p>
      <dl className="proposal-conditions">
        <div><dt>Vendedor</dt><dd>{proposal.seller.name}</dd></div>
        <div><dt>Precio</dt><dd>{listing.price} €</dd></div>
        <div><dt>Superficie</dt><dd>{listing.surface} m²</dd></div>
        <div><dt>Dormitorios</dt><dd>{listing.bedrooms}</dd></div>
        <div><dt>Baños</dt><dd>{listing.bathrooms}</dd></div>
        <div><dt>Personas</dt><dd>{listing.people}</dd></div>
        <div><dt>Alojamiento compartido</dt><dd>{listing.shared_accommodation ? 'Sí' : 'No'}</dd></div>
      </dl>
      {listing.photos[0] && <img className="proposal-photo" src={listing.photos[0]} alt={listing.title} />}
      {proposal.status === 'PENDING' && (
        <div className="proposal-actions">
          {submitting && <p role="status">Guardando respuesta…</p>}
          {seller
            ? <button type="button" className="btn btn--ghost" disabled={disabled}
                onClick={() => respond('CANCEL')}>Cancelar propuesta</button>
            : <>
                <button type="button" className="btn" disabled={disabled}
                  onClick={() => respond('ACCEPT')}>Aceptar propuesta</button>
                <button type="button" className="btn btn--ghost" disabled={disabled}
                  onClick={() => respond('REJECT')}>Rechazar propuesta</button>
              </>}
        </div>
      )}
    </article>
  )
}
