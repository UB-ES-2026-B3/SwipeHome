/**
 * Campo de formulario reutilizable con soporte de error accesible.
 *
 * Props:
 *  - id: string (requerido, vincula label e input)
 *  - label: string
 *  - error: string | undefined (mensaje de error)
 *  - [resto de props de input/select pasados directamente]
 */
export function FormField({ id, label, error, children, ...inputProps }) {
  const errorId = error ? `${id}-error` : undefined

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
        <input
          id={id}
          className={`form-field__input ${error ? 'form-field__input--error' : ''}`}
          aria-invalid={!!error}
          aria-describedby={errorId}
          {...inputProps}
        />
      )}

      {error && (
        <span id={errorId} className="form-field__error" role="alert">
          {error}
        </span>
      )}
    </div>
  )
}
