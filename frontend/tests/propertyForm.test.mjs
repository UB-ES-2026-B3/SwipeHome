import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  MAX_PHOTO_SIZE,
  MAX_PHOTOS,
  validatePhotoContent,
  validatePhotoFile,
  validatePhotoSelection,
  validatePropertyFields,
} from '../src/pages/propertyForm.js'

const validValues = {
  title: 'Piso luminoso',
  street: 'Calle Mayor 1',
  city: 'Barcelona',
  postal_code: '08001',
  description: 'Una descripción válida',
  price: '950.50',
  surface: '65.5',
  bedrooms: '0',
  bathrooms: '1',
  people: '2',
  shared_accommodation: 'No',
}

function photo(name = 'home.jpg', type = 'image/jpeg', size = 1024) {
  return { name, type, size }
}

test('accepts valid fields, including zero bedrooms and decimal limits', () => {
  assert.deepEqual(validatePropertyFields(validValues), {})
  assert.deepEqual(
    validatePropertyFields({ ...validValues, price: '.50', surface: '1000000000' }),
    {},
  )
})

test('rejects missing text, invalid numbers, unsupported enum values and excess precision', () => {
  const errors = validatePropertyFields({
    ...validValues,
    title: '  ',
    price: '10.999',
    surface: '0',
    bedrooms: '-1',
    bathrooms: '1.2',
    people: '',
    shared_accommodation: 'Maybe',
  })

  for (const field of ['title', 'price', 'surface', 'bedrooms', 'bathrooms', 'people', 'shared_accommodation']) {
    assert.ok(errors[field], `expected validation error for ${field}`)
  }
  assert.ok(validatePropertyFields({ ...validValues, shared_accommodation: '' }).shared_accommodation)
})

test('accepts supported photo types up to the inclusive size limit', () => {
  assert.equal(validatePhotoFile(photo('home.webp', 'image/webp', MAX_PHOTO_SIZE)), null)
  assert.equal(validatePhotoFile(photo('home.png', 'image/png')), null)
  assert.equal(validatePhotoFile(photo('home.jpeg', 'image/jpeg')), null)
})

test('rejects unsupported extensions, mismatched MIME types and oversized photos', () => {
  assert.match(validatePhotoFile(photo('home.gif', 'image/gif')), /Formato no admitido/)
  assert.match(validatePhotoFile(photo('home.jpg', 'text/plain')), /no coincide/)
  assert.match(validatePhotoFile(photo('home.jpg', 'image/jpeg', MAX_PHOTO_SIZE + 1)), /5 MB/)
})

test('rejects files that claim an image MIME type but have invalid image signatures', async () => {
  const fakePng = new File(['not a PNG'], 'fake.png', { type: 'image/png' })
  const realPng = new File([
    Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10]),
  ], 'real.png', { type: 'image/png' })
  const realJpeg = new File([
    Uint8Array.from([255, 216, 255, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
  ], 'real.jpg', { type: 'image/jpeg' })
  const realWebp = new File([
    Uint8Array.from([82, 73, 70, 70, 0, 0, 0, 0, 87, 69, 66, 80]),
  ], 'real.webp', { type: 'image/webp' })

  assert.equal(await validatePhotoContent(fakePng), false)
  assert.equal(await validatePhotoContent(realPng), true)
  assert.equal(await validatePhotoContent(realJpeg), true)
  assert.equal(await validatePhotoContent(realWebp), true)
})

test('adds only available valid photos and reports each rejected file without losing existing photos', () => {
  const selection = validatePhotoSelection(
    [photo('valid.png', 'image/png'), photo('bad.gif', 'image/gif'), photo('overflow.jpg')],
    MAX_PHOTOS - 1,
  )

  assert.deepEqual(selection.accepted.map(({ name }) => name), ['valid.png'])
  assert.equal(selection.rejected.length, 2)
  assert.match(selection.rejected[0].reason, /Formato no admitido/)
  assert.match(selection.rejected[1].reason, /máximo 10/)
})
