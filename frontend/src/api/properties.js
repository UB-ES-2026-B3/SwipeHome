import { auth } from '../firebase'

export async function publishProperty(fields, photos) {
  const user = auth.currentUser
  if (!user) return { ok: false, status: 401, data: { error: 'Necesitas iniciar sesión para publicar un inmueble.' } }

  let token
  try {
    token = await user.getIdToken()
  } catch (error) {
    if (['auth/user-token-expired', 'auth/invalid-user-token', 'auth/user-disabled', 'auth/user-not-found'].includes(error?.code)) {
      return { ok: false, status: 401, data: { error: 'Necesitas iniciar sesión para publicar un inmueble.' } }
    }
    throw error
  }
  const form = new FormData()
  const values = {
    title: fields.title,
    street: fields.address,
    city: fields.locality,
    postal_code: fields.postalCode,
    description: fields.description,
    price: fields.price,
    surface: fields.area,
    bedrooms: fields.bedrooms,
    bathrooms: fields.bathrooms,
    people: fields.tenants,
    shared_accommodation: fields.shared === 'yes' ? 'Sí' : 'No',
  }

  for (const [name, value] of Object.entries(values)) form.append(name, value)
  for (const { file } of photos) form.append('photos', file)

  const response = await fetch('/api/inmuebles', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  })
  const data = await response.json()
  return { ok: response.ok, status: response.status, data }
}
