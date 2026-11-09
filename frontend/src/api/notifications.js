import { auth } from '../firebase'

export async function getNotifications({ limit = 10, cursor } = {}) {
  const user = auth.currentUser
  if (!user) return { ok: false, status: 401, data: { error: 'Necesitas iniciar sesión.' } }

  const token = await user.getIdToken()
  const params = new URLSearchParams({ limit: String(limit) })
  if (cursor) params.set('cursor', cursor)

  const response = await fetch(`/api/notificaciones?${params}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  })
  const data = await response.json()
  return { ok: response.ok, status: response.status, data }
}
