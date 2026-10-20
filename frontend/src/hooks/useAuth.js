import { useContext } from 'react'
import { AuthContext } from '../context/AuthContext'

/**
 * Hook para consumir el contexto de autenticación.
 * Debe usarse dentro de un componente envuelto en AuthProvider.
 */
export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth debe usarse dentro de <AuthProvider>')
  }
  return context
}
