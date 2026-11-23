import assert from 'node:assert/strict'
import { test } from 'node:test'
import { clearProposalRequestId, createProposalRequestId, getProposalRequestId, proposalRequestKey } from '../src/api/proposalRequests.js'

function makeStorage() {
  const values = new Map()
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  }
}

test('retains the request id across retries and page reloads until confirmed', () => {
  const storage = makeStorage()
  const key = proposalRequestKey('seller', 'listing', 'match')
  let counter = 0
  const createId = () => `request-${++counter}`
  assert.equal(getProposalRequestId(new Map(), storage, key, createId), 'request-1')
  assert.equal(getProposalRequestId(new Map(), storage, key, createId), 'request-1')
  clearProposalRequestId(new Map(), storage, key)
  assert.equal(getProposalRequestId(new Map(), storage, key, createId), 'request-2')
})

test('separates sellers and candidacies and tolerates unavailable storage', () => {
  const storage = makeStorage()
  const first = proposalRequestKey('seller-1', 'home', 'match-1')
  const otherSeller = proposalRequestKey('seller-2', 'home', 'match-1')
  const otherMatch = proposalRequestKey('seller-1', 'home', 'match-2')
  assert.equal(new Set([first, otherSeller, otherMatch]).size, 3)
  let counter = 0
  const cache = new Map()
  const blocked = { getItem() { throw new Error('blocked') }, setItem() { throw new Error('blocked') }, removeItem() { throw new Error('blocked') } }
  assert.equal(getProposalRequestId(cache, blocked, first, () => `id-${++counter}`), 'id-1')
  assert.equal(getProposalRequestId(cache, blocked, first, () => `id-${++counter}`), 'id-1')
  assert.equal(getProposalRequestId(cache, storage, otherMatch, () => `id-${++counter}`), 'id-2')
  clearProposalRequestId(cache, blocked, first)
})

test('generates distinct secure request ids', () => {
  const first = createProposalRequestId()
  const second = createProposalRequestId()
  assert.notEqual(first, second)
  assert.match(first, /^[a-f0-9-]{32,36}$/i)
})