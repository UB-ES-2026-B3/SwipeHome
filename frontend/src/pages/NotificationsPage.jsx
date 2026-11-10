import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Logo } from '../components/Logo'
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
  
  const [notifications, setNotifications] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [cursor, setCursor] = useState(null)
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  
  // Ref para evitar solicitudes simultáneas
  const isRefreshingRef = useRef(false)

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

  /**
   * Cargar notificaciones del servidor.
   * 
   * @param {string|null} nextCursor - Cursor para paginación. Si es null, carga desde el inicio.
   * @param {boolean} isRefresh - Si es true, es una actualización (no duplica)
   */
  const loadNotifications = async (nextCursor = null, isRefresh = false) => {
    try {
      // CA-06: Evitar solicitudes repetidas
      if (nextCursor === null && isRefreshingRef.current) {
        return
      }

      if (!nextCursor) {
        // CA-01: Consultar al entrar en la pantalla y al recargar
        // CA-03: Se evita duplicar notificaciones ya mostradas
        setLoading(true)
        setError(null)
        isRefreshingRef.current = true
      } else {
        // CA-02: Cargar más resultados conserva los anteriores
        setLoadingMore(true)
      }
      
      // CA-01: Reutiliza GET /api/notificaciones
      // CA-02: Las solicitudes utilizan la sesión existente (vía Authorization header en getNotifications)
      const result = await getNotifications({ cursor: nextCursor })
      
      if (!result.ok) {
        // CA-05: Manejo de errores según status
        if (result.status === 401) {
          // CA-05: Un 401 activa el tratamiento de sesión expirada
          setError('Tu sesión ha caducado. Por favor, inicia sesión de nuevo.')
          await logout()
          navigate('/login')
          return
        }
        
        // CA-05: Un 500 se trata como error reintentable, sin cerrar la sesión
        const errorMessage = result.data?.error || 'No se pudieron cargar las notificaciones. Inténtalo de nuevo.'
        setError(errorMessage)
        return
      }

      const { items = [], cursor: newCursor, has_more } = result.data
      
      // CA-03: Las notificaciones proceden del servidor, no de datos ficticios
      if (nextCursor) {
        // CA-02: Cargar más resultados conserva los anteriores
        setNotifications(prev => [...prev, ...items])
      } else {
        // CA-03: Actualizar no duplica las notificaciones ya mostradas
        setNotifications(items)
      }
      
      setCursor(newCursor || null)
      setHasMore(has_more || false)
    } catch (err) {
      console.error('Error fetching notifications:', err)
      // CA-05: Un fallo se trata como error reintentable
      setError('Hubo un error al cargar las notificaciones. Inténtalo de nuevo.')
    } finally {
      setLoading(false)
      setLoadingMore(false)
      isRefreshingRef.current = false
    }
  }

  // CA-01: Se consultan los avisos al entrar en la pantalla
  useEffect(() => {
    loadNotifications()
  }, [])

  // CA-02: Cargar más resultados
  const handleLoadMore = () => {
    // CA-06: Mientras se actualiza, se evita enviar solicitudes repetidas
    if (cursor && hasMore && !loadingMore && !isRefreshingRef.current) {
      loadNotifications(cursor, false)
    }
  }

  // CA-01: «Actualizar» vuelve a consultar los resultados más recientes
  const handleRefresh = () => {
    // CA-06: Se evita enviar solicitudes repetidas mediante el mismo control
    if (!isRefreshingRef.current) {
      loadNotifications(null, true)
    }
  }

  return (
    <main className="notifications-page">
      <header className="home-page__header">
        <Logo size="sm" to={user?.role === 'SELLER' ? '/vendedor/inicio' : '/comprador/inicio'} />
        <div className="home-page__account">
          <button type="button" className="home-page__profile uniform-action" onClick={() => navigate('/mi-perfil')}>
            Mi perfil
          </button>
          <button type="button" className="home-page__logout uniform-action" onClick={logout}>
            Salir
          </button>
        </div>
      </header>

      <div className="notifications-page__content">
        <div className="notifications-page__top">
          <h1 className="notifications-page__title">Notificaciones</h1>
          <button 
            type="button" 
            className="btn"
            onClick={handleRefresh}
            disabled={loading || isRefreshingRef.current}
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
              disabled={isRefreshingRef.current}
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
                  className="btn"
                  onClick={handleLoadMore}
                  disabled={loadingMore || isRefreshingRef.current}
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
