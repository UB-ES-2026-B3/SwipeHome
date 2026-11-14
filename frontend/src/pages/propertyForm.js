export const MAX_PHOTOS = 10
export const MAX_PHOTO_SIZE = 5 * 1024 * 1024

const ALLOWED_PHOTOS = new Map([
  ['.jpg', 'image/jpeg'],
  ['.jpeg', 'image/jpeg'],
  ['.png', 'image/png'],
  ['.webp', 'image/webp'],
])

export function validatePropertyFields(values) {
  const errors = {}
  const requiredText = [
    ['title', 'El título es obligatorio.'],
    ['street', 'La dirección es obligatoria.'],
    ['city', 'La localidad es obligatoria.'],
    ['postal_code', 'El código postal es obligatorio.'],
    ['description', 'La descripción es obligatoria.'],
  ]

  for (const [field, message] of requiredText) {
    if (!values[field]?.trim()) errors[field] = message
  }

  for (const field of ['price', 'surface']) {
    const value = values[field]?.trim() ?? ''
    const digits = value.replace(/[+.]/g, '')
    if (!/^\+?(?:\d+(?:\.\d{1,2})?|\.\d{1,2})$/.test(value) || digits.length > 10 || Number(value) <= 0) {
      errors[field] = 'Introduce un número mayor que cero con un máximo de dos decimales.'
    }
  }

  for (const [field, minimum, label] of [
    ['bedrooms', 0, 'dormitorios'],
    ['bathrooms', 1, 'baños'],
    ['people', 1, 'personas'],
  ]) {
    const value = values[field]?.trim() ?? ''
    if (!/^\+?\d+$/.test(value) || Number(value) < minimum) {
      errors[field] = `Introduce un número entero válido de ${label}.`
    }
  }

  if (!['Sí', 'No'].includes(values.shared_accommodation)) {
    errors.shared_accommodation = 'Selecciona Sí o No.'
  }
  return errors
}

export function validatePhotoFile(file) {
  const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
  const expectedType = ALLOWED_PHOTOS.get(extension)
  if (!expectedType) {
    return 'Formato no admitido. Usa JPEG, PNG o WebP.'
  }
  if (file.type !== expectedType) {
    return 'El tipo del archivo no coincide con su extensión o no es una imagen admitida.'
  }
  if (file.size > MAX_PHOTO_SIZE) {
    return 'La imagen supera el límite de 5 MB.'
  }
  return null
}

export async function validatePhotoContent(file) {
  const bytes = new Uint8Array(await file.slice(0, 12).arrayBuffer())
  const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()

  if (extension === '.jpg' || extension === '.jpeg') {
    return bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff
  }
  if (extension === '.png') {
    return [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]
      .every((byte, index) => bytes[index] === byte)
  }
  return (
    extension === '.webp' &&
    String.fromCharCode(...bytes.slice(0, 4)) === 'RIFF' &&
    String.fromCharCode(...bytes.slice(8, 12)) === 'WEBP'
  )
}

export function validatePhotoSelection(files, currentCount) {
  const accepted = []
  const rejected = []
  let remaining = Math.max(0, MAX_PHOTOS - currentCount)

  for (const file of files) {
    const reason = validatePhotoFile(file)
    if (reason) {
      rejected.push({ name: file.name, reason })
    } else if (remaining === 0) {
      rejected.push({ name: file.name, reason: 'Se permiten como máximo 10 fotografías.' })
    } else {
      accepted.push(file)
      remaining -= 1
    }
  }
  return { accepted, rejected }
}
