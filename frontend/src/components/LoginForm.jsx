import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login } from '../api/auth'
import { useAuth } from '../hooks/useAuth'
import { FormField } from './FormField'

const EMAIL_ERROR = 'Introduce un email válido.'

function validateForm({ email, password }) {
  const errors = {}
  const trimmedEmail = email.trim()

  if (
    !trimmedEmail ||
    /\s/.test(trimmedEmail) ||
    trimmedEmail.length > 254 ||
    !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)
  ) {
    errors.email = EMAIL_ERROR
  }

  if (!password) {
    errors.password = 'La contraseña es obligatoria.'
  } else if (password.length > 128) {
    errors.password = 'La contraseña no puede superar los 128 caracteres.'
  }

  return errors
}

export function LoginForm({ onSubmit } = {}) {
  const navigate = useNavigate()
  const { setUser } = useAuth()
  const [fields, setFields] = useState({ email: '', password: '' })
  const [fieldErrors, setFieldErrors] = useState({})
  const [serverError, setServerError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  // The ref closes the gap before React renders the disabled button.
  const submissionInProgress = useRef(false)

  function handleChange(e) {
    const { name, value } = e.target
    setFields((prev) => ({ ...prev, [name]: value }))

    if (fieldErrors[name]) {
      setFieldErrors((prev) => ({ ...prev, [name]: undefined }))
    }
    if (serverError) setServerError(null)
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (submissionInProgress.current) return

    const errors = validateForm(fields)
    setFieldErrors(errors)

    if (Object.keys(errors).length > 0) return

    submissionInProgress.current = true
    setSubmitting(true)
    setServerError(null)

    try {
      const credentials = {
        email: fields.email.trim().toLowerCase(),
        password: fields.password,
      }
      const { ok, status, data } = await login(credentials)

      if (ok && status === 200) {
        setUser(data)
        onSubmit?.(data)
        navigate(
          data.role === 'SELLER'
            ? '/vendedor/inicio'
            : '/comprador/inicio',
        )
        return
      }

      if (status === 400) {
        if (data.errors && typeof data.errors === 'object') {
          setFieldErrors(data.errors)
        } else {
          setServerError(data.error || 'Datos inválidos. Revisa el formulario.')
        }
        return
      }

      if (status === 401) {
        setServerError('Email o contraseña incorrectos.')
        return
      }

      setServerError(
        data.error ||
          'No se pudo iniciar sesión. Inténtalo de nuevo.',
      )
    } catch {
      setServerError(
        'No hay conexión con el servidor. Comprueba tu red e inténtalo de nuevo.',
      )
    } finally {
      submissionInProgress.current = false
      setSubmitting(false)
    }
  }

  return (
    <form
      className="register-form"
      onSubmit={handleSubmit}
      noValidate
      aria-label="Formulario de inicio de sesión"
    >
      {serverError && (
        <div className="register-form__server-error" role="alert">
          {serverError}
        </div>
      )}

      <FormField
        id="email"
        label="Email"
        type="email"
        name="email"
        value={fields.email}
        onChange={handleChange}
        autoComplete="email"
        required
        error={fieldErrors.email}
        placeholder="tu@email.com"
      />

      <FormField
        id="password"
        label="Contraseña"
        type="password"
        name="password"
        value={fields.password}
        onChange={handleChange}
        autoComplete="current-password"
        required
        error={fieldErrors.password}
        placeholder="Tu contraseña"
      />

      <button
        type="submit"
        className="register-form__submit"
        disabled={submitting}
        aria-busy={submitting}
      >
        {submitting ? 'Iniciando sesión…' : 'Iniciar sesión'}
      </button>
    </form>
  )
}
