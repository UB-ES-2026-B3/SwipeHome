import { auth } from '../firebase'

/** Publishes a listing using the authenticated Firebase user's ID token. */
export async function publishProperty(values, photos) {
  const firebaseUser = auth.currentUser
  if (!firebaseUser) throw new Error('No hay una sesión autenticada.')

  const token = await firebaseUser.getIdToken()
  const form = new FormData()
  for (const [field, value] of Object.entries(values)) {
    form.append(field, value)
  }
  for (const photo of photos) {
    form.append('photos', photo)
  }

  const response = await fetch('/api/inmuebles', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
    cache: 'no-store',
  })

  let data
  try {
    data = await response.json()
  } catch {
    data = null
  }
  return { ok: response.ok, status: response.status, data }
}
