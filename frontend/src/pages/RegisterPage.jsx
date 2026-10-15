import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { RegisterForm } from '../components/RegisterForm'
import { useAuth } from '../hooks/useAuth'

/**
 * Página de registro (/registro).
 *
 * Si el usuario ya está autenticado, redirige directamente
 * al inicio correspondiente a su rol.
 */
export function RegisterPage() {
  const { user, loading } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (!loading && user) {
      // Ya autenticado: redirigir según rol
      if (user.role === 'SELLER') {
        navigate('/vendedor/inicio', { replace: true })
      } else {
        navigate('/comprador/inicio', { replace: true })
      }
    }
  }, [user, loading, navigate])

  // Mientras se comprueba la sesión inicial, no renderizar el formulario
  if (loading) {
    return (
      <div className="page-loading" aria-label="Cargando…">
        <div className="page-loading__spinner" aria-hidden="true" />
      </div>
    )
  }

  return (
    <main className="auth-page">
      {/* Panel izquierdo: branding */}
      <div className="auth-page__brand" aria-hidden="true">
        <div className="auth-page__brand-content">
          <div className="auth-page__logo">🏠</div>
          <h1 className="auth-page__tagline">SwipeHome</h1>
          <p className="auth-page__subtitle">
            Encuentra tu hogar con un swipe
          </p>
        </div>
        <div className="auth-page__brand-cards">
          {/* Tarjetas decorativas estilo Tinder */}
          <div className="mock-card mock-card--back" aria-hidden="true">
            <div className="mock-card__img mock-card__img--2" />
          </div>
          <div className="mock-card mock-card--front" aria-hidden="true">
            <div className="mock-card__img mock-card__img--1" />
            <div className="mock-card__info">
              <span className="mock-card__title">Piso en Gràcia</span>
              <span className="mock-card__price">950 €/mes</span>
            </div>
            <div className="mock-card__actions">
              <button className="mock-card__btn mock-card__btn--dislike" aria-hidden="true">✕</button>
              <button className="mock-card__btn mock-card__btn--like" aria-hidden="true">♥</button>
            </div>
          </div>
        </div>
      </div>

      {/* Panel derecho: formulario */}
      <div className="auth-page__form-panel">
        <div className="auth-page__form-container">
          <div className="auth-page__form-header">
            <h2 className="auth-page__form-title">Crea tu cuenta</h2>
            <p className="auth-page__form-desc">
              Únete a SwipeHome y empieza a explorar
            </p>
          </div>

          <RegisterForm />

          <p className="auth-page__login-link">
            ¿Ya tienes cuenta?{' '}
            <a href="/login" className="auth-page__link">
              Inicia sesión
            </a>
          </p>
        </div>
      </div>
    </main>
  )
}
