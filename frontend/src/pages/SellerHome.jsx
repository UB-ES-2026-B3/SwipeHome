import { useNavigate } from 'react-router-dom'
import { Logo } from '../components/Logo'
import { useAuth } from '../hooks/useAuth'

/**
 * Inicio del Vendedor (/vendedor/inicio).
 * Destino de navegación tras un registro o login exitoso con rol SELLER.
 * El contenido completo de esta pantalla está fuera del alcance del Sprint 0.
 */
export function SellerHome() {
  const { logout } = useAuth()
  const navigate = useNavigate()
  const publishedProperties = []

  return (
    <main className="seller-dashboard">
      <header className="seller-dashboard__header">
        <Logo size="sm" />
        <div className="seller-dashboard__account">
          <span className="seller-dashboard__role">Vendedor</span>
          <button type="button" className="seller-dashboard__logout" onClick={logout}>
            LogOut
          </button>
        </div>
      </header>

      <div className="seller-dashboard__content">
        <button
          type="button"
          className="seller-dashboard__publish"
          onClick={() => navigate('/publicar')}
        >
          Publicar
        </button>

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
      </div>
    </main>
  )
}
