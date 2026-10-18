import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

/**
 * Inicio del Vendedor (/vendedor/inicio).
 * Destino de navegación tras un registro o login exitoso con rol SELLER.
 * El contenido completo de esta pantalla está fuera del alcance del Sprint 0.
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
          Desde aquí podrás publicar tus inmuebles y gestionar tus anuncios.
          Las funcionalidades completas estarán disponibles próximamente.
        </p>
        <button
          className="home-page__cta"
          onClick={() => navigate('/publicar')}
        >
          Publicar inmueble
        </button>
        {/* Provisional: desbloquea el flujo de logout; libre de mover o rediseñar. */}
        <button type="button" className="home-page__logout" onClick={logout}>
          Cerrar sesión
        </button>
      </div>
    </main>
  )
}
