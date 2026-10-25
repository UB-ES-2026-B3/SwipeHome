import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { registerUser } from '../api/auth'
import { useAuth } from '../hooks/useAuth'
import { FormField } from './FormField'

// ─── Validaciones de campo (US1-1) ───────────────────────────────────────────

/**
 * Valida todos los campos del formulario de registro.
 * Devuelve un objeto { field: errorMessage } con los errores encontrados.
 * Si el objeto está vacío, el formulario es válido.
 *
 * Reglas según la US1 (project_context.md §6):
 *  - name:     2–80 caracteres tras eliminar espacios exteriores
 *  - email:    formato válido, sin espacios interiores, ≤ 254 chars (normalizado)
 *  - password: 8–128 caracteres, con mayúscula, número y símbolo
 *  - role:     'SELLER' o 'BUYER', recibido por la página de registro
 */
function validateForm({ name, email, password, role }) {
  const errors = {}

  // Nombre
  const trimmedName = name.trim()
  if (!trimmedName) {
    errors.name = 'El nombre es obligatorio.'
  } else if (trimmedName.length < 2) {
    errors.name = 'El nombre debe tener al menos 2 caracteres.'
  } else if (trimmedName.length > 80) {
    errors.name = 'El nombre no puede superar los 80 caracteres.'
  }

  // Email: normalizar (trim + minúsculas) y validar
  const trimmedEmail = email.trim().toLowerCase()
  if (!trimmedEmail) {
    errors.email = 'El email es obligatorio.'
  } else if (/\s/.test(trimmedEmail)) {
    errors.email = 'El email no puede contener espacios.'
  } else if (trimmedEmail.length > 254) {
    errors.email = 'El email no puede superar los 254 caracteres.'
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) {
    errors.email = 'Introduce un email válido.'
  }

  // Contraseña: NO se recorta ni se modifica
  if (!password) {
    errors.password = 'La contraseña es obligatoria.'
  } else if (password.length < 8) {
    errors.password = 'La contraseña debe tener al menos 8 caracteres.'
  } else if (!/[A-Z]/.test(password)) {
    errors.password = 'La contraseña debe incluir al menos una mayúscula.'
  } else if (!/\d/.test(password)) {
    errors.password = 'La contraseña debe incluir al menos un número.'
  } else if (!/[^\w\s]/.test(password)) {
    errors.password = 'La contraseña debe incluir al menos un símbolo.'
  } else if (password.length > 128) {
    errors.password = 'La contraseña no puede superar los 128 caracteres.'
  }

  // Rol
  if (role !== 'SELLER' && role !== 'BUYER') {
    errors.role = 'Rol no válido.'
  }

  return errors
}

// ─── Componente ───────────────────────────────────────────────────────────────

/**
 * Props:
 *  - onSuccess: función opcional a llamar después de un registro exitoso
 *    (p.ej. para cerrar el overlay). La redirección de rol la hace siempre.
 */
export function RegisterForm({ onSuccess, role } = {}) {
  const navigate = useNavigate()
  const { setUser } = useAuth()

  const [fields, setFields] = useState({
    name: '',
    email: '',
    password: '',
  })

  // Errores de validación local (campo a campo)
  const [fieldErrors, setFieldErrors] = useState({})
  // Error global (respuesta del servidor: 409, 500, red)
  const [serverError, setServerError] = useState(null)
  // Estado de carga: impide envíos repetidos
  const [submitting, setSubmitting] = useState(false)

  function handleChange(e) {
    const { name, value } = e.target
    setFields((prev) => ({ ...prev, [name]: value }))
    // Limpiar el error del campo en cuanto el usuario empieza a corregir
    if (fieldErrors[name]) {
      setFieldErrors((prev) => ({ ...prev, [name]: undefined }))
    }
    if (serverError) setServerError(null)
  }

  async function handleSubmit(e) {
    e.preventDefault()

    // Validación local antes de enviar (US1-1 / CA-03)
    const errors = validateForm(fields)
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors)
      return
    }

    setSubmitting(true)
    setServerError(null)

    try {
      // Normalizar email antes de enviar (trim + minúsculas)
      // La contraseña NO se modifica
      const payload = {
        name: fields.name.trim(),
        email: fields.email.trim().toLowerCase(),
        password: fields.password,
        role,
      }

      const { ok, status, data } = await registerUser(payload)

      if (ok && status === 201) {
        // CA-02: actualizar estado de autenticación y redirigir según rol
        setUser(data)
        onSuccess?.()
        if (data.role === 'SELLER') {
          navigate('/vendedor/inicio')
        } else {
          navigate('/comprador/inicio')
        }
        return
      }

      // CA-03: errores de validación del servidor (400)
      if (status === 400) {
        if (data.errors && typeof data.errors === 'object') {
          setFieldErrors(data.errors)
        } else {
          setServerError(data.error || 'Datos inválidos. Revisa el formulario.')
        }
        return
      }

      // CA-04: email ya registrado (409)
      if (status === 409) {
        setFieldErrors((prev) => ({
          ...prev,
          email: data.error || 'Este email ya está registrado.',
        }))
        return
      }

      // CA-05: error de servidor (500 u otros)
      setServerError(
        data.error ||
          'No se pudo completar el registro. Inténtalo de nuevo.',
      )
    } catch {
      // CA-05: fallo de conexión
      setServerError(
        'No hay conexión con el servidor. Comprueba tu red e inténtalo de nuevo.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form
      className="register-form"
      onSubmit={handleSubmit}
      noValidate
      aria-label="Formulario de registro"
    >
      {/* Error global del servidor */}
      {serverError && (
        <div className="register-form__server-error" role="alert">
          {serverError}
        </div>
      )}

      {/* Nombre */}
      <FormField
        id="name"
        label="Nombre"
        type="text"
        name="name"
        value={fields.name}
        onChange={handleChange}
        autoComplete="name"
        maxLength={80}
        required
        error={fieldErrors.name}
        placeholder="Tu nombre completo"
      />

      {/* Email */}
      <FormField
        id="email"
        label="Email"
        type="email"
        name="email"
        value={fields.email}
        onChange={handleChange}
        autoComplete="email"
        maxLength={254}
        required
        error={fieldErrors.email}
        placeholder="tu@email.com"
      />

      {/* Contraseña */}
      <FormField
        id="password"
        label="Contraseña"
        type="password"
        name="password"
        value={fields.password}
        onChange={handleChange}
        autoComplete="new-password"
        required
        error={fieldErrors.password}
        placeholder="Mínimo 8 caracteres, mayúscula, número y símbolo"
      />

      <button
        type="submit"
        className="register-form__submit"
        disabled={submitting}
        aria-busy={submitting}
      >
        {submitting ? 'Registrando…' : 'Crear cuenta'}
      </button>
    </form>
  )
}
