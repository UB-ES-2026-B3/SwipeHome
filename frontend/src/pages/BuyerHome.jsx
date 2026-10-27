import { useAuth } from '../hooks/useAuth'
import { useNavigate } from 'react-router-dom'
import { Logo } from '../components/Logo'

/**
 * Inicio del Comprador (/comprador/inicio).
 * Destino de navegación tras un registro o login exitoso con rol BUYER.
 * El contenido completo (swipe, exploración) está fuera del alcance del Sprint 0.
 */
export function BuyerHome() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <main className="home-page home-page--buyer">
      <header className="home-page__header">
        <Logo size="sm" />
        <button type="button" className="home-page__profile" onClick={() => navigate('/mi-perfil')}>
          Mi perfil
        </button>
      </header>
      <div className="home-page__content">
        <div className="home-page__logo" aria-hidden="true">🔍</div>
        <h1 className="home-page__title">
          ¡Bienvenido, {user?.name || 'Comprador'}!
        </h1>
        <p className="home-page__role-badge home-page__role-badge--buyer">
          Comprador
        </p>
        <p className="home-page__desc">
          Pronto podrás explorar inmuebles y hacer swipe para encontrar tu
          hogar ideal. Las funcionalidades completas estarán disponibles
          próximamente.
        </p>
        <div className="home-page__swipe-preview" aria-hidden="true">
          <div className="mock-card mock-card--preview">
            <div className="mock-card__img mock-card__img--1" />
            <div className="mock-card__info">
              <span className="mock-card__title">Próximamente…</span>
              <span className="mock-card__price">Empieza a hacer swipe</span>
            </div>
          </div>
        </div>
        {/* Provisional: desbloquea el flujo de logout; libre de mover o rediseñar. */}
        <button type="button" className="home-page__logout" onClick={logout}>Cerrar sesión</button>
      </div>
    </main>
  )
}
