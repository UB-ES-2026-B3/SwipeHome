/**
 * Módulo de llamadas a la API de autenticación.
 *
 * Todos los fetch incluyen credentials: 'include' para que el navegador
 * envíe y reciba la cookie de sesión (HttpOnly, SameSite=Lax).
 *
 * El backend Django espera un token CSRF en la cabecera X-CSRFToken para
 * las peticiones mutables. Se obtiene primero con GET /api/auth/register
 * y se reutiliza mientras dure la sesión.
 */

let csrfToken = null

/**
 * Obtiene el token CSRF del backend (GET /api/auth/register).
 * El valor se cachea en memoria para la sesión del navegador.
 */
async function getCsrfToken() {
  if (csrfToken) return csrfToken

  const response = await fetch('/api/auth/register', {
    method: 'GET',
    credentials: 'include',
  })

  if (!response.ok) {
    throw new Error('No se pudo obtener el token CSRF.')
  }

  const data = await response.json()
  csrfToken = data.csrfToken
  return csrfToken
}

/**
 * Envía los datos de registro al backend.
 *
 * @param {{ name: string, email: string, password: string, role: 'SELLER' | 'BUYER' }} payload
 * @returns {{ ok: boolean, status: number, data: object }}
 */
export async function registerUser(payload) {
  const token = await getCsrfToken()

  const response = await fetch('/api/auth/register', {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': token,
    },
    body: JSON.stringify(payload),
  })

  const data = await response.json()
  return { ok: response.ok, status: response.status, data }
}

/**
 * Consulta la sesión activa para recuperar el usuario autenticado.
 * Utilizado al recargar la página para mantener el estado de autenticación.
 *
 * @returns {{ id: number, name: string, email: string, role: string } | null}
 */
export async function fetchCurrentUser() {
  const response = await fetch('/api/auth/me', {
    method: 'GET',
    credentials: 'include',
  })

  if (response.status === 401) return null
  if (!response.ok) throw new Error('Error al consultar la sesión.')

  return response.json()
}
