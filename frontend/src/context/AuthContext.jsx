import { createContext, useCallback, useEffect, useState } from 'react'
import { fetchCurrentUser } from '../api/auth'

/**
 * Contexto global de autenticación.
 *
 * Estado:
 *  - user: objeto { id, name, email, role } o null
 *  - loading: true mientras se consulta la sesión al iniciar/recargar
 *
 * Acciones:
 *  - setUser(user): establece el usuario tras un registro o login exitoso
 *  - clearUser(): elimina el usuario del estado (logout futuro)
 */
export const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  // Al montar la aplicación, consulta la sesión activa para recuperar
  // el estado de autenticación si el usuario ya tenía una sesión válida.
  useEffect(() => {
    fetchCurrentUser()
      .then((currentUser) => {
        setUser(currentUser)
      })
      .catch(() => {
        // Error de red o servidor: se trata como no autenticado
        setUser(null)
      })
      .finally(() => {
        setLoading(false)
      })
  }, [])

  const clearUser = useCallback(() => setUser(null), [])

  return (
    <AuthContext.Provider value={{ user, loading, setUser, clearUser }}>
      {children}
    </AuthContext.Provider>
  )
}
