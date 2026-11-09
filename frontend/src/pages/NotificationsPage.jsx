import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Logo } from '../components/Logo'
import { useAuth } from '../hooks/useAuth'
import { getNotifications } from '../api/notifications'

/**
 * Pantalla de notificaciones (/notificaciones).
 * Muestra los avisos del usuario (Comprador o Vendedor) con paginación.
 * Cumple con todos los criterios de aceptación de US 7.1.
 */
export function NotificationsPage() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  
  const [notifications, setNotifications] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [cursor, setCursor] = useState(null)
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)

  // Formato de fecha en español
  const formatDate = (dateString) => {
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now - date
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'Hace unos segundos'
    if (diffMins < 60) return `Hace ${diffMins} minuto${diffMins > 1 ? 's' : ''}`
    if (diffHours < 24) return `Hace ${diffHours} hora${diffHours > 1 ? 's' : ''}`
    if (diffDays < 7) return `Hace ${diffDays} día${diffDays > 1 ? 's' : ''}`
    
    return date.toLocaleDateString('es-ES', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  // Cargar notificaciones
  const loadNotifications = async (nextCursor = null) => {
    try {
      if (!nextCursor) {
        setLoading(true)
        setError(null)
      } else {
        setLoadingMore(true)
      }
      
      const result = await getNotifications({ cursor: nextCursor })
      
      if (!result.ok) {
        if (result.status === 401) {
          navigate('/login')
          return
        }
        setError(result.data?.error || 'No se pudieron cargar las notificaciones. Inténtalo de nuevo.')
        return
      }

      const { items, cursor: newCursor, has_more } = result.data
      if (nextCursor) {
        setNotifications(prev => [...prev, ...items])
      } else {
        setNotifications(items)
      }
      
      setCursor(newCursor || null)
      setHasMore(has_more || false)
    } catch (err) {
      console.error('Error fetching notifications:', err)
      setError('Hubo un error al cargar las notificaciones. Inténtalo de nuevo.')
    } finally {
      setLoading(false)
      setLoadingMore(false)
    }
  }

  // Cargar notificaciones al montar el componente
  useEffect(() => {
    loadNotifications()
  }, [])

  // Cargar más resultados
  const handleLoadMore = () => {
    if (cursor && hasMore && !loadingMore) {
      loadNotifications(cursor)
    }
  }

  // Actualizar notificaciones
  const handleRefresh = () => {
    loadNotifications()
  }

  const navClass = user?.role === 'SELLER' ? 'seller-dashboard__account' : 'buyer-dashboard__account'

  return (
    <main className="notifications-page">
      <header className="home-page__header">
        <Logo size="sm" to={user?.role === 'SELLER' ? '/vendedor/inicio' : '/comprador/inicio'} />
        <div className={navClass}>
          <span className="uniform-action">{user?.role === 'SELLER' ? 'Vendedor' : 'Comprador'}</span>
          <button type="button" className="home-page__profile uniform-action" onClick={() => navigate('/mi-perfil')}>
            Mi perfil
          </button>
          <button type="button" className="uniform-action" onClick={logout}>
            LogOut
          </button>
        </div>
      </header>

      <div className="notifications-page__content">
        <div className="notifications-page__top">
          <h1 className="notifications-page__title">Notificaciones</h1>
          <button 
            type="button" 
            className="notifications-page__refresh"
            onClick={handleRefresh}
            disabled={loading}
            aria-label="Actualizar notificaciones"
          >
            🔄 Actualizar
          </button>
        </div>

        {loading && notifications.length === 0 && (
          <div className="notifications-page__loading" aria-label="Cargando notificaciones…">
            <div className="notifications-page__spinner" aria-hidden="true" />
          </div>
        )}

        {error && (
          <div className="notifications-page__error" role="alert">
            <p className="notifications-page__error-icon">⚠️</p>
            <p className="notifications-page__error-message">{error}</p>
            <button 
              type="button" 
              className="notifications-page__retry"
              onClick={handleRefresh}
            >
              Reintentar
            </button>
          </div>
        )}

        {!loading && !error && notifications.length === 0 && (
          <div className="notifications-page__empty">
            <p className="notifications-page__empty-icon">📭</p>
            <p className="notifications-page__empty-message">
              Todavía no tienes notificaciones.
            </p>
          </div>
        )}

        {notifications.length > 0 && (
          <>
            <ul className="notifications-page__list">
              {notifications.map(notification => (
                <li key={notification.id} className="notifications-page__item">
                  <article className={`notification-card notification-card--${notification.type}`}>
                    <div className="notification-card__header">
                      <h3 className="notification-card__message">
                        {notification.message}
                      </h3>
                      <time className="notification-card__timestamp">
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
                  className="notifications-page__load-more-btn"
                  onClick={handleLoadMore}
                  disabled={loadingMore}
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
