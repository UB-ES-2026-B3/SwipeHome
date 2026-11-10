import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getNotifications } from '../api/notifications'
import { Logo } from '../components/Logo'
import { useAuth } from '../hooks/useAuth'

function formatNotificationDate(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('es-ES', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

function notificationMessage(notification) {
  if (notification.buyer?.name && notification.listing?.title) {
    return `${notification.buyer.name} ha mostrado interés en ${notification.listing.title}.`
  }
  return notification.message
}

/**
 * Inicio del Vendedor (/vendedor/inicio).
 * Destino de navegación tras un registro o login exitoso con rol SELLER.
 * Inicio del vendedor y acceso al formulario de publicación.
 */
export function SellerHome() {
  const { logout } = useAuth()
  const navigate = useNavigate()
  const publishedProperties = []
  const [notifications, setNotifications] = useState([])
  const [nextCursor, setNextCursor] = useState(null)
  const nextCursorRef = useRef(null)
  const [notificationsStatus, setNotificationsStatus] = useState('loading')
  const [notificationsError, setNotificationsError] = useState('')

  const loadNotifications = useCallback(async (reset = true) => {
    setNotificationsStatus('loading')
    setNotificationsError('')
    try {
      const result = await getNotifications(reset ? {} : { cursor: nextCursorRef.current })
      if (!result.ok) {
        setNotificationsError(result.data?.error || 'No se pudieron cargar los avisos.')
        setNotificationsStatus('error')
        return
      }
      const items = result.data.items || []
      setNotifications((current) => reset ? items : [...current, ...items])
      setNextCursor(result.data.next_cursor)
      nextCursorRef.current = result.data.next_cursor
      setNotificationsStatus('ready')
    } catch {
      setNotificationsError('No hay conexión con el servidor. Inténtalo de nuevo.')
      setNotificationsStatus('error')
    }
  }, [])

  useEffect(() => {
    loadNotifications()
  }, [loadNotifications])

  return (
    <main className="seller-dashboard">
      <header className="seller-dashboard__header">
        <Logo size="sm" to="/vendedor/inicio" />
        <div className="seller-dashboard__account">
          <span className="seller-dashboard__role uniform-action">Vendedor</span>
          <button type="button" className="uniform-action" onClick={() => navigate('/notificaciones')}>
            Notificaciones
          </button>
          <button type="button" className="seller-dashboard__profile uniform-action" onClick={() => navigate('/mi-perfil')}>
            Mi perfil
          </button>
          <button type="button" className="seller-dashboard__logout uniform-action" onClick={logout}>
            LogOut
          </button>
        </div>
      </header>

      <div className="seller-dashboard__content">
        <nav aria-label="Menú del vendedor">
          <button
            type="button"
            className="seller-dashboard__publish"
            onClick={() => navigate('/publicar')}
          >
            Publicar
          </button>
        </nav>

        <section className="seller-dashboard__list" aria-labelledby="published-properties-title">
          <h1 id="published-properties-title">Mis inmuebles publicados</h1>
          {publishedProperties.length > 0 ? (
            <ul>
              {publishedProperties.map((property) => (
                <li className="seller-dashboard__property" key={property.id}>
                  <span>{property.name}</span>
                  <span>
                    {property.requests} {property.requests === 1 ? 'solicitud' : 'solicitudes'}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="seller-dashboard__empty">
              <strong>Sin inmuebles publicados</strong>
              <span>0 solicitudes</span>
            </div>
          )}
        </section>

        <section className="seller-dashboard__notifications" aria-labelledby="notifications-title">
          <div className="seller-dashboard__section-header">
            <h2 id="notifications-title">Avisos</h2>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => loadNotifications()}
              disabled={notificationsStatus === 'loading'}
            >
              Actualizar
            </button>
          </div>
          {notificationsStatus === 'loading' && (
            <p className="seller-dashboard__message">Cargando avisos…</p>
          )}
          {notificationsStatus === 'error' && (
            <div className="seller-dashboard__message seller-dashboard__message--error" role="alert">
              <p>{notificationsError}</p>
              <button type="button" className="btn btn--ghost" onClick={() => loadNotifications()}>
                Reintentar
              </button>
            </div>
          )}
          {notificationsStatus === 'ready' && notifications.length === 0 && (
            <p className="seller-dashboard__message">
              Todavía no has recibido intereses en tus viviendas.
            </p>
          )}
          {notificationsStatus === 'ready' && notifications.length > 0 && (
            <>
              <ul className="seller-dashboard__notifications-list">
                {notifications.map((notification) => (
                  <li className="seller-dashboard__notification" key={notification.id}>
                    <p>{notificationMessage(notification)}</p>
                    <time dateTime={notification.created_at}>
                      {formatNotificationDate(notification.created_at)}
                    </time>
                  </li>
                ))}
              </ul>
              {nextCursor && (
                <button
                  type="button"
                  className="btn btn--ghost seller-dashboard__load-more"
                  onClick={() => loadNotifications(false)}
                  disabled={notificationsStatus === 'loading'}
                >
                  Cargar más
                </button>
              )}
            </>
          )}
        </section>
      </div>
    </main>
  )
}
