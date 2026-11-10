import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

/**
 * Inicio del Vendedor (/vendedor/inicio).
 * Destino de navegación tras un registro o login exitoso con rol SELLER.
 * Inicio del vendedor y acceso al formulario de publicación.
 */
export function SellerHome() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <main className="home-page home-page--seller">
      <div className="home-page__content">
        <div className="home-page__logo" aria-hidden="true">🏠</div>
        <h1 className="home-page__title">
          ¡Bienvenido, {user?.name || 'Vendedor'}!
        </h1>
        <p className="home-page__role-badge home-page__role-badge--seller">
          Vendedor
        </p>
        <p className="home-page__desc">
          Publica un inmueble para que los compradores puedan encontrarlo.
        </p>
        <nav className="home-page__seller-menu" aria-label="Menú del vendedor">
          <button
            type="button"
            className="home-page__cta"
            onClick={() => navigate('/publicar')}
          >
            Publicar
          </button>
        </nav>
        {/* Provisional: desbloquea el flujo de logout; libre de mover o rediseñar. */}
        <button type="button" className="home-page__logout" onClick={logout}>
          Cerrar sesión
        </button>
      </div>
    </main>
  )
}
