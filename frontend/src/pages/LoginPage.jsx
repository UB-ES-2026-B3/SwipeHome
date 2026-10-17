import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Logo } from '../components/Logo'
import { LoginForm } from '../components/LoginForm'
import { useAuth } from '../hooks/useAuth'

export function LoginPage() {
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
        <h1 className="auth-page__title">Bienvenido de nuevo</h1>
        <p className="auth-page__subtitle">Accede a tu cuenta de SwipeHome.</p>

        <LoginForm />

        <p className="register-form__login-link" style={{ marginTop: '16px' }}>
          ¿No tienes cuenta?{' '}
          <a href="/registro">Regístrate</a>
        </p>
      </div>
    </div>
  )
}
