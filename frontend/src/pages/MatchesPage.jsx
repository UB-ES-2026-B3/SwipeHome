import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { getMatches, sendProposal } from '../api/properties'
import { Logo } from '../components/Logo'
import { useAuth } from '../hooks/useAuth'

function formatDate(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('es-ES', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

export function MatchesPage() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [matches, setMatches] = useState([])
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState('')
  const [nextCursor, setNextCursor] = useState(null)
  const [sending, setSending] = useState(null)
  const [notice, setNotice] = useState(null)
  const cursorRef = useRef(null)
  const loadingRef = useRef(false)
  const sendingRef = useRef(false)

  const loadMatches = useCallback(async (reset = true) => {
    if (loadingRef.current) return
    loadingRef.current = true
    try {
      const result = await getMatches(reset ? {} : { cursor: cursorRef.current })
      if (result.status === 401) {
        if (await logout()) {
          navigate('/login', { replace: true })
        } else {
          setError('La sesión ha caducado y no se pudo cerrar. Reintenta desde el aviso de sesión.')
          setStatus('error')
        }
        return
      }
      if (!result.ok) {
        setError(result.data?.error || 'No se pudieron cargar tus matches.')
        setStatus('error')
        return
      }
      const items = result.data.items || []
      setMatches((current) => reset ? items : [...current, ...items])
      cursorRef.current = result.data.next_cursor || null
      setNextCursor(cursorRef.current)
      setStatus('ready')
    } catch {
      setError('No hay conexión con el servidor. Inténtalo de nuevo.')
      setStatus('error')
    } finally {
      loadingRef.current = false
    }
  }, [logout, navigate])

  useEffect(() => {
    loadMatches()
  }, [loadMatches])

  const homePath = user?.role === 'SELLER' ? '/vendedor/inicio' : '/comprador/inicio'
  const seller = user?.role === 'SELLER'

  function storageKey(match) {
    return `swipehome:proposal:${user.uid}:${match.id}`
  }

  async function propose(match) {
    if (sendingRef.current || loadingRef.current) return
    const key = storageKey(match)
    const saved = sessionStorage.getItem(key)
    if (!saved && (match.proposal_pending || match.listing.available === false)) return

    sendingRef.current = true
    setSending(match.id)
    setNotice(null)
    try {
      const intention = saved ?? crypto.randomUUID()
      sessionStorage.setItem(key, intention)
      const result = await sendProposal(match.listing.id, match.buyer.id, intention)
      if (result.status < 500) sessionStorage.removeItem(key)
      if (result.status === 401 && await logout()) {
        navigate('/login', { replace: true })
        return
      }
      if (!result.ok) {
        setNotice({ error: result.data?.error || 'No se pudo enviar la propuesta. Inténtalo de nuevo.' })
        if (result.status === 409 || result.status === 404) await loadMatches()
        return
      }
      setNotice({
        id: result.data.id,
        message: result.data.status === 'PENDING' ? 'Propuesta enviada.' : 'El envío ya se había registrado.',
      })
      if (result.data.status === 'PENDING') {
        setMatches((current) => current.map((row) => row.listing.id === match.listing.id
          ? { ...row, proposal_pending: true }
          : row))
      } else {
        await loadMatches()
      }
    } catch {
      setNotice({ error: 'No hay conexión con el servidor. Puedes reintentar el envío.' })
    } finally {
      sendingRef.current = false
      setSending(null)
    }
  }

  return (
    <main className="matches-page">
      <header className="home-page__header">
        <Logo size="sm" to={homePath} />
        <div className="matches-page__header-actions">
          <button type="button" className="uniform-action" onClick={() => navigate(homePath)}>
            Volver al inicio
          </button>
          <Link className="uniform-action" to="/propuestas">Propuestas</Link>
          <button type="button" className="home-page__profile uniform-action" onClick={() => navigate('/mi-perfil')}>
            Mi perfil
          </button>
          <button type="button" className="buyer-dashboard__logout uniform-action" onClick={logout}>
            Salir
          </button>
        </div>
      </header>
      <section className="matches-page__content" aria-labelledby="matches-title">
        <div className="matches-page__heading">
          <div>
            <h1 id="matches-title">Mis matches</h1>
            <p>
              Aquí aparecen únicamente los intereses que ambas partes han confirmado.
            </p>
          </div>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => {
              setStatus('loading')
              setError('')
              loadMatches()
            }}
            disabled={status === 'loading' || sending !== null}
          >
            Actualizar
          </button>
        </div>
        {notice?.error && <p role="alert" className="matches-page__message matches-page__message--error">{notice.error}</p>}
        {notice?.id && (
          <p role="status" className="matches-page__message">
            {notice.message} <Link to={`/propuestas/${notice.id}`}>Ver propuesta</Link>
          </p>
        )}
        {status === 'loading' && (
          <p className="matches-page__message" role="status">Cargando matches…</p>
        )}
        {status === 'error' && (
          <div className="matches-page__message matches-page__message--error" role="alert">
            <p>{error}</p>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => {
                setStatus('loading')
                setError('')
                loadMatches()
              }}
            >
              Reintentar
            </button>
          </div>
        )}
        {status === 'ready' && matches.length === 0 && (
          <div className="matches-page__message">
            <p>Aún no tienes matches confirmados.</p>
            {user?.role === 'BUYER' && (
              <p>Un interés enviado no aparecerá aquí hasta que el Vendedor lo acepte.</p>
            )}
          </div>
        )}
        {status === 'ready' && matches.length > 0 && (
          <>
            <ul className="matches-page__list">
              {matches.map((match) => {
                const retry = seller && sessionStorage.getItem(storageKey(match))
                const canPropose = seller && (retry || (!match.proposal_pending && match.listing.available !== false))
                return (
                  <li className="matches-page__item" key={match.id}>
                    <article>
                      <h2>{match.listing.title}</h2>
                      <p className="matches-page__location">
                        {[match.listing.street, match.listing.city].filter(Boolean).join(' · ')}
                      </p>
                      {match.listing.available === false && <p>Vivienda no disponible</p>}
                      <p>
                        {seller
                          ? `Comprador/a: ${match.buyer.name}`
                          : 'Vendedor y tú habéis confirmado el interés en esta vivienda.'}
                      </p>
                      <time dateTime={match.created_at}>
                        Confirmado el {formatDate(match.created_at)}
                      </time>
                      {seller && match.proposal_pending && <p>Hay una propuesta pendiente para esta vivienda.</p>}
                      {canPropose && (
                        <button type="button" className="btn btn--ghost" onClick={() => propose(match)}
                          disabled={sending !== null}>
                          {sending === match.id ? 'Enviando propuesta…' : retry ? 'Reintentar envío' : 'Enviar propuesta'}
                        </button>
                      )}
                    </article>
                  </li>
                )
              })}
            </ul>
            {nextCursor && (
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => {
                  setStatus('loading')
                  loadMatches(false)
                }}
                disabled={status === 'loading' || sending !== null}
              >
                Cargar más matches
              </button>
            )}
          </>
        )}
      </section>
    </main>
  )
}
