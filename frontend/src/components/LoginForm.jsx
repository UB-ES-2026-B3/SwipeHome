import { useState } from 'react'
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
  const [fields, setFields] = useState({ email: '', password: '' })
  const [fieldErrors, setFieldErrors] = useState({})

  function handleChange(e) {
    const { name, value } = e.target
    setFields((prev) => ({ ...prev, [name]: value }))

    if (fieldErrors[name]) {
      setFieldErrors((prev) => ({ ...prev, [name]: undefined }))
    }
  }

  function handleSubmit(e) {
    e.preventDefault()

    const errors = validateForm(fields)
    setFieldErrors(errors)

    if (Object.keys(errors).length > 0) return

    onSubmit?.({
      email: fields.email.trim().toLowerCase(),
      password: fields.password,
    })
  }

  return (
    <form
      className="register-form"
      onSubmit={handleSubmit}
      noValidate
      aria-label="Formulario de inicio de sesión"
    >
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

      <button type="submit" className="register-form__submit">
        Iniciar sesión
      </button>
    </form>
  )
}
