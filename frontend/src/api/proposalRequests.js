export function proposalRequestKey(userId, listingId, matchId) {
  return `swipehome.proposal:${JSON.stringify([userId, listingId, matchId])}`
}

export function createProposalRequestId() {
  if (typeof globalThis.crypto?.randomUUID === 'function') return globalThis.crypto.randomUUID()
  const bytes = new Uint8Array(16)
  globalThis.crypto.getRandomValues(bytes)
  return Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
}

export function getProposalRequestId(cache, storage, key, createId) {
  if (cache.has(key)) return cache.get(key)
  let requestId
  try {
    requestId = storage?.getItem(key)
  } catch {
    requestId = null
  }
  requestId ||= createId()
  cache.set(key, requestId)
  try {
    storage?.setItem(key, requestId)
  } catch {
    return requestId
  }
  return requestId
}

export function clearProposalRequestId(cache, storage, key) {
  cache.delete(key)
  try {
    storage?.removeItem(key)
  } catch {
    return
  }
}