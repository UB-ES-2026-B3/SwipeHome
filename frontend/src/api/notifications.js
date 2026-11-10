import { auth } from '../firebase'

/**
 * Obtiene las notificaciones del usuario autenticado.
 * 
 * US 7.2: Conectar la pantalla con la API de notificaciones
 * 
 * Criterios de aceptación implementados:
 * - CA-01: Reutiliza GET /api/notificaciones, definido previamente en US4
 * - CA-02: Las solicitudes utilizan la sesión existente (Authorization: Bearer token)
 * - CA-03: Cursor para paginación
 * - CA-05: Manejo de status codes (401, 500, etc.)
 * - CA-06: Cache 'no-store' para evitar datos obsoletos
 * 
 * @param {Object} options
 * @param {number} options.limit - Cantidad de notificaciones por página (default: 10)
 * @param {string} options.cursor - Cursor para paginación
 * @returns {Promise<{ok: boolean, status: number, data: Object}>}
 */
export async function getNotifications({ limit = 10, cursor } = {}) {
  const user = auth.currentUser
  // CA-05: Manejo de usuario no autenticado
  if (!user) {
    return { 
      ok: false, 
      status: 401, 
      data: { error: 'Necesitas iniciar sesión.' } 
    }
  }

  // CA-02: Obtener token de la sesión actual
  let token
  try {
    token = await user.getIdToken()
  } catch (error) {
    console.error('Error getting ID token:', error)
    return { 
      ok: false, 
      status: 401, 
      data: { error: 'Error de autenticación. Por favor, inicia sesión de nuevo.' } 
    }
  }

  // Construir parámetros de query
  const params = new URLSearchParams({ limit: String(limit) })
  if (cursor) params.set('cursor', cursor)

  try {
    // CA-01: GET /api/notificaciones con sesión existente
    // CA-02: Header Authorization con Bearer token
    // CA-06: cache 'no-store' para evitar datos cacheados
    const response = await fetch(`/api/notificaciones?${params}`, {
      method: 'GET',
      headers: { 
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      cache: 'no-store',
    })

    // CA-05: Leer el cuerpo de la respuesta
    const data = await response.json()

    // CA-05: Retornar status y datos
    // - 200: Éxito
    // - 401: Sesión expirada (será manejado en NotificationsPage)
    // - 500: Error del servidor (será reintentable)
    return { 
      ok: response.ok, 
      status: response.status, 
      data 
    }
  } catch (error) {
    console.error('Network error fetching notifications:', error)
    return { 
      ok: false, 
      status: 0, 
      data: { error: 'Error de conexión. Comprueba tu red e inténtalo de nuevo.' } 
    }
  }
}
