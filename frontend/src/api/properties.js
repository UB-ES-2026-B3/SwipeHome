import { auth } from '../firebase'
import { apiUrl } from './baseUrl'

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

  const response = await fetch(apiUrl(path), {
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

export function getActiveProperties(signal) {
  return authenticatedRequest('/api/inmuebles', { signal })
}

export function exploreProperties(cursor = null) {
  const query = new URLSearchParams({ limit: '20' })
  if (cursor) query.set('cursor', cursor)
  return authenticatedRequest(`/api/inmuebles/explorar?${query}`)
}

function getMatchPage(path, cursor, signal, propertyId) {
  const query = new URLSearchParams({ limit: '20' })
  if (cursor) query.set('cursor', cursor)
  if (propertyId) query.set('inmueble', propertyId)
  return authenticatedRequest(`${path}?${query}`, { method: 'GET', signal })
}

export function getConfirmedMatches(cursor = null, signal, propertyId) {
  return getMatchPage('/api/matches', cursor, signal, propertyId)
}

export function getPendingCandidates(cursor = null, signal, propertyId) {
  return getMatchPage('/api/candidatos', cursor, signal, propertyId)
}

export function decideCandidate(matchId, decision) {
  return authenticatedRequest(`/api/matches/${encodeURIComponent(matchId)}/decision-vendedor`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision }),
  })
}

export function getProposals(cursor = null, signal) {
  const query = new URLSearchParams({ limit: '20' })
  if (cursor) query.set('cursor', cursor)
  return authenticatedRequest(`/api/propuestas?${query}`, { method: 'GET', signal })
}

export function getProposal(proposalId, signal) {
  return authenticatedRequest(`/api/propuestas/${encodeURIComponent(proposalId)}`, { method: 'GET', signal })
}

export function createProposal(listingId, matchId, requestId) {
  return authenticatedRequest('/api/propuestas', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ listing_id: listingId, match_id: matchId, request_id: requestId }),
  })
}

export function resolveProposal(proposalId, action) {
  return authenticatedRequest(`/api/propuestas/${encodeURIComponent(proposalId)}/${action}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
}

export function decideProperty(propertyId, decision) {
  return authenticatedRequest(`/api/inmuebles/${encodeURIComponent(propertyId)}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision }),
  })
}

export function getSearchPreferences() {
  return authenticatedRequest('/api/exploracion/filtros', { method: 'GET' })
}

export function saveSearchPreferences(preferences) {
  return authenticatedRequest('/api/exploracion/filtros', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(preferences),
  })
}

export function resetSearchPreferences() {
  return authenticatedRequest('/api/exploracion/filtros', { method: 'DELETE' })
}

export function getFilterOptions() {
  return authenticatedRequest('/api/inmuebles/opciones-filtro', { method: 'GET' })
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
