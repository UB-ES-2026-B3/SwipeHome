import { onAuthStateChanged, signOut } from 'firebase/auth'
import { createContext, useCallback, useEffect, useRef, useState } from 'react'
import { fetchCurrentUser, logout as firebaseLogout } from '../api/auth'
import { AuthErrorBanner } from '../components/AuthErrorBanner'
import { auth } from '../firebase'

/**
 * Contexto global de autenticación, sincronizado con Firebase Auth.
 *
 * Estado:
 *  - user: objeto { uid, name, email, role } o null
 *  - loading: true mientras no se sabe quién es el usuario. Sigue en true si el
 *    perfil no se pudo cargar por un fallo del servidor o de la red: así
 *    PrivateRoute no redirige y un fallo nunca parece un cierre de sesión.
 *  - authError: null o { kind, message } que muestra AuthErrorBanner
 *
 * Acciones:
 *  - setUser(user): establece el usuario tras un registro o login exitoso
 *  - clearUser(): elimina el usuario del estado
 *  - logout(): cierra la sesión de Firebase
 *  - retry(): vuelve a pedir el perfil del usuario actual
 *  - dismissAuthError(): oculta el aviso de cuenta incompleta
 *
 * Regla 401 frente a 5xx (§3 de la spec):
 *  - 401 → signOut, interfaz sin sesión.
 *  - 404 → signOut y aviso de cuenta incompleta.
 *  - 5xx, fallo de red o respuesta lenta → aviso con "Reintentar" y la sesión SE CONSERVA.
 */
export const AuthContext = createContext(null)

// El backend está en el plan gratuito de Render: tras 15 min sin tráfico se
// duerme y tarda ~1 min en despertar. Si /me no responde en este tiempo se
// muestra el aviso para que el usuario nunca vea un spinner sin salida.
const SLOW_REQUEST_MS = 4000

const SERVER_WAKING = {
  kind: 'unavailable',
  message: 'El servidor está despertando, puede tardar un momento.',
}
const SERVER_UNAVAILABLE = {
  kind: 'unavailable',
  message: 'No hemos podido comprobar tu sesión. El servidor puede estar despertando.',
}
const ACCOUNT_INCOMPLETE = {
  kind: 'incomplete',
  message: 'Tu cuenta está incompleta. Contacta con el equipo de SwipeHome.',
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [authError, setAuthError] = useState(null)
  const [loggingOut, setLoggingOut] = useState(false)
  const logoutInProgress = useRef(false)
  // Cada petición de perfil tiene un id: solo se aplica la respuesta de la última.
  const requestId = useRef(0)

  const loadProfile = useCallback(async (firebaseUser) => {
    const id = ++requestId.current
    const isCurrent = () => id === requestId.current && auth.currentUser?.uid === firebaseUser.uid
    const slowTimer = setTimeout(() => {
      if (isCurrent()) setAuthError(SERVER_WAKING)
    }, SLOW_REQUEST_MS)

    try {
      const { ok, status, data } = await fetchCurrentUser(firebaseUser)
      if (!isCurrent()) return
      if (ok) {
        setUser(data)
        setAuthError(null)
        setLoading(false)
      } else if (status === 401) {
        setAuthError(null)
        await signOut(auth)
      } else if (status === 404) {
        setAuthError(ACCOUNT_INCOMPLETE)
        await signOut(auth)
      } else {
        setAuthError(SERVER_UNAVAILABLE)
      }
    } catch {
      // Fallo de red: se conserva la sesión.
      if (isCurrent()) setAuthError(SERVER_UNAVAILABLE)
    } finally {
      clearTimeout(slowTimer)
    }
  }, [])

  useEffect(
    () =>
      onAuthStateChanged(auth, (firebaseUser) => {
        if (firebaseUser) {
          loadProfile(firebaseUser)
          return
        }
        requestId.current += 1 // descarta cualquier petición de perfil en curso
        setUser(null)
        setLoading(false)
        // El aviso de cuenta incompleta debe sobrevivir al signOut que lo provoca.
        setAuthError((current) => (current?.kind === 'incomplete' ? current : null))
      }),
    [loadProfile],
  )

  const retry = useCallback(() => {
    if (auth.currentUser) {
      setAuthError(SERVER_WAKING)
      loadProfile(auth.currentUser)
    } else {
      setAuthError(null)
    }
  }, [loadProfile])

  const clearUser = useCallback(() => setUser(null), [])
  const dismissAuthError = useCallback(() => setAuthError(null), [])
  const logout = useCallback(async () => {
    if (logoutInProgress.current) return false
    logoutInProgress.current = true
    setLoggingOut(true)
    try {
      await firebaseLogout()
      return true
    } catch {
      setAuthError({ kind: 'logout', message: 'No se pudo cerrar la sesión. Vuelve a pulsar Cerrar sesión.' })
      return false
    } finally {
      logoutInProgress.current = false
      setLoggingOut(false)
    }
  }, [])

  return (
    <AuthContext.Provider
      value={{ user, loading, authError, setUser, clearUser, logout, loggingOut, retry, dismissAuthError }}
    >
      {/* Solución temporal: el aviso vive aquí para no tocar los componentes existentes. */}
      <AuthErrorBanner />
      {children}
    </AuthContext.Provider>
  )
}
