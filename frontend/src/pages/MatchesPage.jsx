import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getMatches } from '../api/properties'
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
  const cursorRef = useRef(null)
  const loadingRef = useRef(false)

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

  return (
    <main className="matches-page">
      <header className="home-page__header">
        <Logo size="sm" to={homePath} />
        <div className="matches-page__header-actions">
          <button type="button" className="uniform-action" onClick={() => navigate(homePath)}>
            Volver al inicio
          </button>
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
            disabled={status === 'loading'}
          >
            Actualizar
          </button>
        </div>
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
              {matches.map((match) => (
                <li className="matches-page__item" key={match.id}>
                  <article>
                    <h2>{match.listing.title}</h2>
                    <p className="matches-page__location">
                      {[match.listing.street, match.listing.city].filter(Boolean).join(' · ')}
                    </p>
                    {match.listing.available === false && <p>Vivienda no disponible</p>}
                    <p>
                      {user?.role === 'BUYER'
                        ? `Vendedor y tú habéis confirmado el interés en esta vivienda.`
                        : `Comprador/a: ${match.buyer.name}`}
                    </p>
                    <time dateTime={match.created_at}>
                      Confirmado el {formatDate(match.created_at)}
                    </time>
                  </article>
                </li>
              ))}
            </ul>
            {nextCursor && (
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => {
                  setStatus('loading')
                  loadMatches(false)
                }}
                disabled={status === 'loading'}
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
