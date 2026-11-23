import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { decideCandidate, getPendingCandidates } from '../api/properties'
import { useAuth } from '../hooks/useAuth'

export function SellerCandidates() {
  const { logout } = useAuth()
  const navigate = useNavigate()
  const [candidates, setCandidates] = useState([])
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState('')
  const [busyId, setBusyId] = useState(null)
  const [nextCursor, setNextCursor] = useState(null)
  const cursorRef = useRef(null)
  const loadingRef = useRef(false)
  const decisionRef = useRef(false)

  const loadCandidates = useCallback(async (reset = true) => {
    if (loadingRef.current) return
    loadingRef.current = true
    try {
      const result = await getPendingCandidates(
        reset ? {} : { cursor: cursorRef.current },
      )
      if (result.status === 401) {
        if (await logout()) {
          navigate('/login', { replace: true })
        } else {
          setError('La sesión ha caducado y no se pudo cerrar. Reintenta desde el aviso de sesión.')
          setStatus('error')
        }
        return false
      }
      if (!result.ok) {
        setError(result.data?.error || 'No se pudieron cargar las candidaturas.')
        setStatus('error')
        return false
      }
      const items = result.data.items || []
      setCandidates((current) => reset ? items : [...current, ...items])
      cursorRef.current = result.data.next_cursor || null
      setNextCursor(cursorRef.current)
      setStatus('ready')
      return true
    } catch {
      setError('No hay conexión con el servidor. Inténtalo de nuevo.')
      setStatus('error')
      return false
    } finally {
      loadingRef.current = false
    }
  }, [logout, navigate])

  useEffect(() => {
    loadCandidates()
  }, [loadCandidates])

  async function handleDecision(candidate, decision) {
    if (decisionRef.current) return
    decisionRef.current = true
    setBusyId(candidate.id)
    setError('')
    setFeedback('')
    try {
      const result = await decideCandidate(candidate.id, decision)
      if (result.status === 401) {
        if (await logout()) {
          navigate('/login', { replace: true })
        } else {
          setError('La sesión ha caducado y no se pudo cerrar. Reintenta desde el aviso de sesión.')
        }
        return
      }
      const saved = result.data?.decision
      const validResult =
        result.ok &&
        saved?.id === candidate.id &&
        saved?.seller_decision === decision &&
        (decision === 'ACCEPT'
          ? result.data?.match?.listing_id === candidate.listing.id
          : result.data?.match === null)
      if (validResult) {
        setCandidates((current) => current.filter((item) => item.id !== candidate.id))
        setFeedback(
          decision === 'ACCEPT'
            ? `Match confirmado con ${candidate.buyer.name} para ${candidate.listing.title}.`
            : `Candidatura de ${candidate.buyer.name} rechazada para ${candidate.listing.title}.`,
        )
      } else if (result.status === 409) {
        setStatus('loading')
        if (await loadCandidates()) {
          setFeedback('La candidatura ya se había resuelto. Se actualizó la lista.')
        }
      } else {
        setError(
          result.data?.error ||
            'No se pudo confirmar la decisión. Puedes reintentarlo.',
        )
      }
    } catch {
      setError('No hay conexión para guardar la decisión. Puedes reintentarlo.')
    } finally {
      decisionRef.current = false
      setBusyId(null)
    }
  }

  return (
    <section className="seller-dashboard__candidates" aria-labelledby="candidates-title">
      <div className="seller-dashboard__section-header">
        <h2 id="candidates-title">Candidaturas pendientes</h2>
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => {
            setStatus('loading')
            setError('')
            loadCandidates()
          }}
          disabled={status === 'loading' || busyId !== null}
        >
          Actualizar
        </button>
      </div>
      {status === 'loading' && (
        <p className="seller-dashboard__message" role="status">Cargando candidaturas…</p>
      )}
      {status === 'error' && (
        <div className="seller-dashboard__message seller-dashboard__message--error" role="alert">
          <p>{error}</p>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => {
              setStatus('loading')
              setError('')
              loadCandidates()
            }}
          >
            Reintentar
          </button>
        </div>
      )}
      {status === 'ready' && error && (
        <p role="alert" className="seller-dashboard__message seller-dashboard__message--error">{error}</p>
      )}
      {feedback && <p className="seller-dashboard__feedback" role="status">{feedback}</p>}
      {status === 'ready' && candidates.length === 0 && (
        <p className="seller-dashboard__message">
          No tienes candidaturas pendientes. Los matches confirmados están en «Mis matches».
        </p>
      )}
      {status === 'ready' && candidates.length > 0 && (
        <>
          <ul className="seller-dashboard__candidate-list">
            {candidates.map((candidate) => (
              <li className="seller-dashboard__candidate" key={candidate.id}>
                <div>
                  <h3>{candidate.buyer.name}</h3>
                  <p>
                    Interesado/a en <strong>{candidate.listing.title}</strong>
                    {candidate.listing.city ? ` · ${candidate.listing.city}` : ''}
                  </p>
                </div>
                <div className="seller-dashboard__candidate-actions">
                  <button
                    type="button"
                    className="btn btn--dark"
                    onClick={() => handleDecision(candidate, 'ACCEPT')}
                    disabled={busyId !== null}
                  >
                    {busyId === candidate.id ? 'Guardando…' : 'Aceptar'}
                  </button>
                  <button
                    type="button"
                    className="btn btn--ghost"
                    onClick={() => handleDecision(candidate, 'REJECT')}
                    disabled={busyId !== null}
                  >
                    Rechazar
                  </button>
                </div>
              </li>
            ))}
          </ul>
          {nextCursor && (
            <button
              type="button"
              className="btn btn--ghost seller-dashboard__load-more"
              onClick={() => {
                setStatus('loading')
                loadCandidates(false)
              }}
              disabled={busyId !== null}
            >
              Cargar más candidaturas
            </button>
          )}
        </>
      )}
    </section>
  )
}
