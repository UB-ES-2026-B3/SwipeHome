import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { DashboardHeader } from '../components/DashboardHeader'
import { useAuth } from '../hooks/useAuth'
import { getNotifications } from '../api/notifications'

/**
 * Pantalla de notificaciones (/notificaciones).
 * Muestra los avisos del usuario (Comprador o Vendedor) con paginación.
 * 
 * US 7.1: Pantalla de notificaciones
 * US 7.2: Conexión con API y gestión de errores
 * 
 * Criterios de aceptación:
 * - Reutiliza GET /api/notificaciones (US4)
 * - Usa la sesión existente (Authorization: Bearer token)
 * - Consulta al entrar y al recargar
 * - Botón "Actualizar" vuelve a consultar sin duplicar
 * - Evita solicitudes repetidas mientras se actualiza
 * - Cargar más conserva los anteriores
 * - Errores iniciales permiten reintentar
 * - Fallos en actualización conservan avisos visibles
 * - 401: Cierra sesión y redirige a login
 * - 500: Error reintentable sin cerrar sesión
 * - Solo datos del servidor, no ficticios
 */
export function NotificationsPage() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const homePath = user?.role === 'SELLER' ? '/vendedor/inicio' : '/comprador/inicio'
  
  const [notifications, setNotifications] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [cursor, setCursor] = useState(null)
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  
  const isRefreshingRef = useRef(false)
  const isLoadingMoreRef = useRef(false)

  const formatDate = (dateString) => {
    const date = new Date(dateString)
    if (Number.isNaN(date.getTime())) return dateString
    return date.toLocaleDateString('es-ES', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const loadNotifications = useCallback(async (nextCursor = null) => {
    const loadingMoreRequest = Boolean(nextCursor)
    if (isRefreshingRef.current || isLoadingMoreRef.current) return

    if (loadingMoreRequest) {
      isLoadingMoreRef.current = true
      setLoadingMore(true)
    } else {
      isRefreshingRef.current = true
      setLoading(true)
      setError(null)
    }

    try {
      const result = await getNotifications({ cursor: nextCursor })
      
      if (!result.ok) {
        if (result.status === 401) {
          setError('Tu sesión ha caducado. Por favor, inicia sesión de nuevo.')
          await logout()
          navigate('/login')
          return
        }
        
        const errorMessage = result.data?.error || 'No se pudieron cargar las notificaciones. Inténtalo de nuevo.'
        setError(errorMessage)
        return
      }

      const { items = [], next_cursor: newCursor } = result.data

      if (loadingMoreRequest) {
        setNotifications((previous) => {
          const knownIds = new Set(previous.map((notification) => notification.id))
          const uniqueItems = items.filter((notification) => {
            if (knownIds.has(notification.id)) return false
            knownIds.add(notification.id)
            return true
          })
          return [...previous, ...uniqueItems]
        })
      } else {
        setNotifications(items)
      }
      
      setCursor(newCursor || null)
      setHasMore(Boolean(newCursor))
    } catch (err) {
      console.error('Error fetching notifications:', err)
      setError('Hubo un error al cargar las notificaciones. Inténtalo de nuevo.')
    } finally {
      if (loadingMoreRequest) {
        isLoadingMoreRef.current = false
        setLoadingMore(false)
      } else {
        isRefreshingRef.current = false
        setLoading(false)
      }
    }
  }, [logout, navigate])

  useEffect(() => {
    const task = window.setTimeout(() => loadNotifications(), 0)
    return () => window.clearTimeout(task)
  }, [loadNotifications])

  const handleLoadMore = () => {
    if (cursor && hasMore && !isLoadingMoreRef.current && !isRefreshingRef.current) {
      loadNotifications(cursor)
    }
  }

  const handleRefresh = () => {
    if (!isRefreshingRef.current && !isLoadingMoreRef.current) {
      loadNotifications()
    }
  }

  return (
    <main className="notifications-page">
      <DashboardHeader />

      <div className="notifications-page__content">
        <Link className="btn btn--ghost uniform-action dashboard-back-link" to={homePath}>
          <span aria-hidden="true">&larr;</span> Volver al inicio
        </Link>
        <div className="notifications-page__top">
          <h1 className="notifications-page__title">Notificaciones</h1>
          <button 
            type="button" 
            className="btn"
            onClick={handleRefresh}
            disabled={loading || loadingMore}
            aria-label="Actualizar notificaciones"
          >
            Actualizar
          </button>
        </div>

        {loading && notifications.length === 0 && (
          <div className="notifications-page__loading" aria-label="Cargando notificaciones…">
            <div className="notifications-page__spinner" aria-hidden="true" />
          </div>
        )}

        {error && notifications.length === 0 && (
          <div className="notifications-page__error" role="alert">
            <p className="notifications-page__error-message">{error}</p>
            <button
              type="button"
              className="btn btn--error"
              onClick={handleRefresh}
              disabled={loading || loadingMore}
            >
              Reintentar
            </button>
          </div>
        )}

        {!loading && !error && notifications.length === 0 && (
          <div className="notifications-page__empty">
            <p className="notifications-page__empty-message">
              Todavía no tienes notificaciones.
            </p>
          </div>
        )}

        {notifications.length > 0 && (
          <>
            {error && (
              <div className="notifications-page__error-inline" role="alert">
                <p className="notifications-page__error-message">{error}</p>
                <button
                  type="button"
                  className="btn btn--error"
                  onClick={handleRefresh}
                  disabled={loading || loadingMore}
                >
                  Reintentar
                </button>
              </div>
            )}
            
            <ul className="notifications-page__list">
              {notifications.map(notification => (
                <li key={notification.id} className="notifications-page__item">
                  <article className={`notification-card notification-card--${notification.type}`}>
                    <div className="notification-card__header">
                      <h3 className="notification-card__message">
                        {notification.message}
                      </h3>
                      <time className="notification-card__timestamp" dateTime={notification.created_at}>
                        {formatDate(notification.created_at)}
                      </time>
                    </div>

                    {notification.listing && (
                      <div className="notification-card__metadata">
                        <div className="notification-card__property">
                          <span className="notification-card__label">Inmueble:</span>
                          <span className="notification-card__value">
                            {notification.listing.title}
                          </span>
                        </div>

                        {notification.buyer && (
                          <div className="notification-card__buyer">
                            <span className="notification-card__label">Comprador:</span>
                            <span className="notification-card__value">
                              {notification.buyer.name}
                            </span>
                          </div>
                        )}
                      </div>
                    )}
                  </article>
                </li>
              ))}
            </ul>

            {hasMore && (
              <div className="notifications-page__load-more">
                <button 
                  type="button"
                  className="btn"
                  onClick={handleLoadMore}
                  disabled={loadingMore || loading}
                >
                  {loadingMore ? 'Cargando...' : 'Cargar más'}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </main>
  )
}
