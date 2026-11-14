import { useAuth } from '../hooks/useAuth'

/**
 * Aviso global de problemas al comprobar la sesión.
 *
 * TEMPORAL: lo renderiza AuthProvider para no tocar los componentes existentes.
 * No es un patrón a copiar; el equipo de frontend puede moverlo o rediseñarlo.
 *
 * - unavailable: servidor lento o caído. "Reintentar" siempre visible.
 * - logout: el servidor no confirmó el cierre; permite reintentar la misma acción.
 * - incomplete: cuenta sin perfil (404). Se puede cerrar.
 */
export function AuthErrorBanner() {
  const { authError, retry, logout, dismissAuthError } = useAuth()
  if (!authError) return null

  return (
    <div className="auth-banner" role="alert">
      <span className="auth-banner__message">{authError.message}</span>
      {authError.kind === 'unavailable' ? (
        <button type="button" className="auth-banner__action" onClick={retry}>
          Reintentar
        </button>
      ) : authError.kind === 'logout' ? (
        <button type="button" className="auth-banner__action" onClick={logout}>
          Reintentar cierre de sesión
        </button>
      ) : (
        <button type="button" className="auth-banner__action" onClick={dismissAuthError}>
          Cerrar
        </button>
      )}
    </div>
  )
}
