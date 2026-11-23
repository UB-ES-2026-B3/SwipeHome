/**
 * URL del backend para las llamadas a la API.
 *
 * VITE_API_BASE_URL vacía (local con el proxy de Vite, y Render con su rewrite)
 * deja las rutas relativas: '/api/...'. En Azure Static Web Apps no hay proxy
 * hacia el backend, así que se define con la URL de Container Apps y las
 * peticiones van a '<base>/api/...' (Django responde con cabeceras CORS).
 *
 * En `node --test` import.meta.env no existe: la base queda vacía.
 */
const API_BASE_URL =
  typeof import.meta.env === 'undefined' ? '' : (import.meta.env.VITE_API_BASE_URL ?? '')

/** Une base y ruta sin barras duplicadas: la ruta siempre empieza por '/'. */
export function joinApiUrl(base, path) {
  return (base ?? '').replace(/\/+$/, '') + path
}

/** Ruta de la API ('/api/...') resuelta contra VITE_API_BASE_URL. */
export function apiUrl(path) {
  return joinApiUrl(API_BASE_URL, path)
}
