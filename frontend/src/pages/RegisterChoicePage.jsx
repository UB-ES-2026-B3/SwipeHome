import { useNavigate } from 'react-router-dom'
import { Logo } from '../components/Logo'

export function RegisterChoicePage() {
  const navigate = useNavigate()

  return (
    <div className="auth-page">
      <div className="auth-page__inner">
        <div style={{ marginBottom: '24px' }}>
          <Logo size="sm" />
        </div>
        <h1 className="auth-page__title">¿Qué quieres hacer?</h1>
        <p className="auth-page__subtitle">Elige cómo quieres usar SwipeHome.</p>
        <div className="register-choice">
          <button type="button" className="register-form__submit" onClick={() => navigate('/registro/comprador')}>
            Buscar vivienda · Comprador
          </button>
          <button type="button" className="register-choice__secondary" onClick={() => navigate('/registro/vendedor')}>
            Publicar vivienda · Vendedor
          </button>
        </div>
        <p className="register-form__login-link">
          ¿Ya tienes cuenta? <a href="/login">Inicia sesión</a>
        </p>
      </div>
    </div>
  )
}
