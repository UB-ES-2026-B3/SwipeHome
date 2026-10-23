/**
 * Módulo de llamadas de autenticación (Firebase Auth + backend Django).
 *
 * - El registro lo hace el backend (POST /api/auth/register), que valida y crea
 *   el usuario en Firebase. Después se inicia sesión con el SDK para tener token.
 * - El login lo hace el SDK de Firebase directamente; Django no participa.
 * - El perfil se pide a GET /api/auth/me con `Authorization: Bearer <ID token>`.
 *
 * Sin cookies ni CSRF. Todas las funciones devuelven { ok, status, data }, el mismo
 * contrato que consumen LoginForm y RegisterForm. Los fallos de Firebase se traducen
 * a los códigos que ya entienden (401 credenciales, 400 datos, 429 demasiados
 * intentos, 500 resto). Un fallo de red se lanza como excepción.
 */
import { signInWithCustomToken, signInWithEmailAndPassword, signOut } from 'firebase/auth'
import { auth } from '../firebase'

const NETWORK_ERROR = 'auth/network-request-failed'

// El SDK puede devolver cualquiera de estos según la protección contra
// enumeración de emails: todos significan "credenciales incorrectas".
const INVALID_CREDENTIALS = new Set([
  'auth/invalid-credential',
  'auth/invalid-login-credentials',
  'auth/user-not-found',
  'auth/wrong-password',
  'auth/user-disabled',
])

// Al pedir el token: la sesión de Firebase ya no es válida (equivale a un 401).
const SESSION_GONE = new Set([
  'auth/user-token-expired',
  'auth/invalid-user-token',
  'auth/user-disabled',
  'auth/user-not-found',
])

function signInFailure(error) {
  const code = error?.code
  if (code === NETWORK_ERROR) throw error
  if (INVALID_CREDENTIALS.has(code)) {
    return { ok: false, status: 401, data: { error: 'Email o contraseña incorrectos.' } }
  }
  if (code === 'auth/invalid-email') {
    return { ok: false, status: 400, data: { errors: { email: 'Introduce un email válido.' } } }
  }
  if (code === 'auth/missing-password') {
    return { ok: false, status: 400, data: { errors: { password: 'Introduce la contraseña.' } } }
  }
  if (code === 'auth/too-many-requests') {
    return {
      ok: false,
      status: 429,
      data: { error: 'Demasiados intentos fallidos. Espera unos minutos e inténtalo de nuevo.' },
    }
  }
  return { ok: false, status: 500, data: { error: 'No se pudo iniciar sesión. Inténtalo de nuevo.' } }
}

/**
 * Registra al usuario en el backend y, si va bien, inicia sesión en Firebase.
 *
 * @param {{ name: string, email: string, password: string, role: 'SELLER' | 'BUYER' }} payload
 * @returns {Promise<{ ok: boolean, status: number, data: object }>}
 */
export async function registerUser(payload) {
  const response = await fetch('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const data = await response.json()
  if (!response.ok) return { ok: false, status: response.status, data }

  try {
    await signInWithEmailAndPassword(auth, payload.email, payload.password)
  } catch {
    // La cuenta ya existe: reintentar el registro daría 409. Hay que iniciar sesión.
    return {
      ok: false,
      status: 500,
      data: { error: 'Tu cuenta se ha creado, pero no se pudo iniciar sesión. Ve a "Iniciar sesión".' },
    }
  }
  return { ok: true, status: response.status, data }
}

/**
 * Inicia sesión con Firebase y devuelve el perfil del backend.
 *
 * @param {{ email: string, password: string }} credentials
 * @returns {Promise<{ ok: boolean, status: number, data: object }>}
 */
export async function login(credentials) {
  let firebaseUser
  try {
    const result = await signInWithEmailAndPassword(auth, credentials.email, credentials.password)
    firebaseUser = result.user
  } catch (error) {
    return signInFailure(error)
  }

  const result = await fetchCurrentUser(firebaseUser)
  if (result.status === 401) {
    // Acaba de iniciar sesión: un 401 aquí es un fallo, no unas credenciales malas.
    return { ok: false, status: 500, data: { error: 'No se pudo iniciar sesión. Inténtalo de nuevo.' } }
  }
  return result
}

/**
 * Pide el perfil del usuario de Firebase indicado (por defecto, el actual).
 * Lanza una excepción si falla la red: eso NO es un cierre de sesión.
 *
 * @returns {Promise<{ ok: boolean, status: number, data: object | null }>}
 *   200 perfil { uid, name, email, role } · 401 sin sesión válida ·
 *   404 cuenta incompleta (sin perfil) · 5xx fallo del servidor
 */
export async function fetchCurrentUser(firebaseUser = auth.currentUser) {
  if (!firebaseUser) return { ok: false, status: 401, data: null }

  let token
  try {
    token = await firebaseUser.getIdToken()
  } catch (error) {
    if (SESSION_GONE.has(error?.code)) return { ok: false, status: 401, data: null }
    throw error
  }

  const response = await fetch('/api/auth/me', {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  })
  const data = await response.json()
  return { ok: response.ok, status: response.status, data }
}

/** Cierra la sesión de Firebase. AuthContext se entera por onAuthStateChanged. */
export async function logout() {
  const user = auth.currentUser
  if (!user) return signOut(auth)
  let token
  try {
    token = await user.getIdToken()
  } catch (error) {
    if (SESSION_GONE.has(error?.code)) return signOut(auth)
    throw error
  }
  const response = await fetch('/api/auth/logout', {
    method: 'POST', headers: { Authorization: `Bearer ${token}` }, cache: 'no-store',
  })
  if (!response.ok) throw new Error('No se pudo cerrar la sesión. Inténtalo de nuevo.')
  return signOut(auth)
}

/** Actualiza campos editables y renueva la sesión cuando cambia el email. */
export async function updateProfile(values) {
  return accountMutation('/api/auth/me', 'PATCH', values)
}

/** Reautentica en el backend y conserva acceso con el SDK tras cambiar la contraseña. */
export async function changePassword(currentPassword, newPassword) {
  return accountMutation('/api/auth/me/password', 'POST', {
    current_password: currentPassword,
    new_password: newPassword,
  })
}

async function accountMutation(path, method, values) {
  const user = auth.currentUser
  if (!user) return { ok: false, status: 401, data: null }
  const token = await user.getIdToken()
  const response = await fetch(path, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(values),
    cache: 'no-store',
  })
  const data = await response.json()
  if (!response.ok) return { ok: false, status: response.status, data }
  if (data.custom_token) {
    const continuity = data.custom_token
    delete data.custom_token
    try {
      await signInWithCustomToken(auth, continuity)
    } catch {
      // El cambio ya persistió: nunca presentarlo como una operación fallida.
      return {
        ok: true, status: response.status,
        data: { ...data, reauthentication_required: true },
      }
    }
  }
  return { ok: true, status: response.status, data }
}
