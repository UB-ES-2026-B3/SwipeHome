import { auth } from '../firebase'

const SESSION_GONE = new Set([
  'auth/user-token-expired',
  'auth/invalid-user-token',
  'auth/user-disabled',
  'auth/user-not-found',
])

async function authenticatedRequest(path, options = {}) {
  const user = auth.currentUser
  if (!user) return { ok: false, status: 401, data: { error: 'Necesitas iniciar sesión.' } }

  let token
  try {
    token = await user.getIdToken()
  } catch (error) {
    if (SESSION_GONE.has(error?.code)) {
      return { ok: false, status: 401, data: { error: 'Necesitas iniciar sesión.' } }
    }
    throw error
  }

  const response = await fetch(path, {
    ...options,
    headers: { ...options.headers, Authorization: `Bearer ${token}` },
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

export function getActiveProperties() {
  return authenticatedRequest('/api/inmuebles')
}

export function exploreProperties(cursor = null) {
  const query = new URLSearchParams({ limit: '20' })
  if (cursor) query.set('cursor', cursor)
  return authenticatedRequest(`/api/inmuebles/explorar?${query}`)
}

export function decideProperty(propertyId, decision) {
  return authenticatedRequest(`/api/inmuebles/${encodeURIComponent(propertyId)}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision }),
  })
}

export function publishProperty(fields, photos) {
  const values = {
    title: fields.title,
    street: fields.street ?? fields.address,
    city: fields.city ?? fields.locality,
    postal_code: fields.postal_code ?? fields.postalCode,
    description: fields.description,
    price: fields.price,
    surface: fields.surface ?? fields.area,
    bedrooms: fields.bedrooms,
    bathrooms: fields.bathrooms,
    people: fields.people ?? fields.tenants,
    shared_accommodation:
      fields.shared_accommodation ??
      (fields.shared === 'yes' ? 'Sí' : fields.shared === 'no' ? 'No' : ''),
  }
  const form = new FormData()
  for (const [name, value] of Object.entries(values)) {
    form.append(name, value)
  }
  for (const photo of photos) {
    form.append('photos', photo?.file ?? photo)
  }

  return authenticatedRequest('/api/inmuebles', { method: 'POST', body: form })
}
