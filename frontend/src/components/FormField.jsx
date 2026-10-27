/**
 * Campo de formulario reutilizable con soporte de error accesible.
 *
 * Props:
 *  - id: string (requerido, vincula label e input)
 *  - label: string
 *  - error: string | undefined (mensaje de error)
 *  - [resto de props de input/select pasados directamente]
 */
export function FormField({ id, label, error, children, type, ...inputProps }) {
  const [passwordVisible, setPasswordVisible] = useState(false)
  const errorId = error ? `${id}-error` : undefined
  const isPassword = type === 'password'

  return (
    <div className="form-field">
      <label htmlFor={id} className="form-field__label">
        {label}
      </label>

      {children ? (
        // Render de select u otros elementos personalizados
        <div
          className={`form-field__input-wrapper ${error ? 'form-field__input-wrapper--error' : ''}`}
          aria-describedby={errorId}
        >
          {children}
        </div>
      ) : (
        <div className="form-field__input-wrapper">
          <input
            id={id}
            className={`form-field__input ${isPassword ? 'form-field__input--password' : ''} ${error ? 'form-field__input--error' : ''}`}
            aria-invalid={!!error}
            aria-describedby={errorId}
            type={isPassword && passwordVisible ? 'text' : type}
            {...inputProps}
          />
          {isPassword && (
            <button
              type="button"
              className="form-field__password-toggle"
              onClick={() => setPasswordVisible((visible) => !visible)}
              aria-label={passwordVisible ? 'Ocultar contraseña' : 'Mostrar contraseña'}
              aria-pressed={passwordVisible}
            >
              {passwordVisible ? 'Ocultar' : 'Ver'}
            </button>
          )}
        </div>
      )}

      {error && (
        <span id={errorId} className="form-field__error" role="alert">
          {error}
        </span>
      )}
    </div>
  )
}
import { useState } from 'react'
