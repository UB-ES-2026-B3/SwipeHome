import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Logo } from '../components/Logo'
import { RegisterForm } from '../components/RegisterForm'
import { useAuth } from '../hooks/useAuth'

/**
 * Página de registro standalone (/registro).
 * Se usa cuando el usuario accede directamente a la URL.
 * El registro desde la landing usa el overlay en LandingPage.
 */
export function RegisterPage() {
  const { user, loading } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (!loading && user) {
      navigate(
        user.role === 'SELLER' ? '/vendedor/inicio' : '/comprador/inicio',
        { replace: true },
      )
    }
  }, [user, loading, navigate])

  if (loading) {
    return (
      <div className="page-loading" aria-label="Cargando…">
        <div className="page-loading__spinner" aria-hidden="true" />
      </div>
    )
  }

  return (
    <div className="auth-page">
      <div className="auth-page__inner">
        <div style={{ marginBottom: '24px' }}>
          <Logo size="sm" />
        </div>
        <h1 className="auth-page__title">Crea tu cuenta</h1>
        <p className="auth-page__subtitle">Únete a SwipeHome. Es gratis.</p>

        <RegisterForm />

        <p className="register-form__login-link" style={{ marginTop: '16px' }}>
          ¿Ya tienes cuenta?{' '}
          <a href="/login">Inicia sesión</a>
        </p>
      </div>
    </div>
  )
}
