import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { publishProperty } from '../api/properties'
import { FormField } from '../components/FormField'
import { Logo } from '../components/Logo'

const MAX_PHOTOS = 10
const MAX_PHOTO_SIZE = 5 * 1024 * 1024
const ACCEPTED_PHOTO_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp'])

const initialFields = {
  title: '',
  address: '',
  locality: '',
  postalCode: '',
  description: '',
  price: '',
  area: '',
  bedrooms: '',
  bathrooms: '',
  tenants: '',
  shared: '',
}

function validateFields(fields) {
  const errors = {}
  const textFields = [
    ['title', 'El título es obligatorio.'],
    ['address', 'La calle y el número son obligatorios.'],
    ['locality', 'La localidad es obligatoria.'],
    ['postalCode', 'El código postal es obligatorio.'],
    ['description', 'La descripción es obligatoria.'],
  ]

  for (const [field, message] of textFields) {
    if (!fields[field].trim()) errors[field] = message
  }

  const positiveNumbers = [
    ['price', 'Introduce un precio mayor que cero.'],
    ['area', 'Introduce una superficie mayor que cero.'],
  ]
  for (const [field, message] of positiveNumbers) {
    if (fields[field] === '' || !Number.isFinite(Number(fields[field])) || Number(fields[field]) <= 0) {
      errors[field] = message
    }
  }

  const integerFields = [
    ['bedrooms', 0, 'Introduce un número entero igual o mayor que cero.'],
    ['bathrooms', 1, 'Introduce al menos un baño entero.'],
    ['tenants', 1, 'Introduce al menos una persona.'],
  ]
  for (const [field, minimum, message] of integerFields) {
    const value = Number(fields[field])
    if (
      fields[field] === '' ||
      !Number.isInteger(value) ||
      value < minimum
    ) {
      errors[field] = message
    }
  }

  if (!fields.shared) errors.shared = 'Selecciona Sí o No.'
  return errors
}

function validatePhotos(photos) {
  if (photos.length === 0) return 'Añade al menos una fotografía.'
  return null
}

const FIELD_ALIASES = {
  title: 'title',
  street: 'address',
  city: 'locality',
  postal_code: 'postalCode',
  description: 'description',
  price: 'price',
  surface: 'area',
  bedrooms: 'bedrooms',
  bathrooms: 'bathrooms',
  people: 'tenants',
  shared_accommodation: 'shared',
}

export function PublishPropertyPage() {
  const navigate = useNavigate()
  const [fields, setFields] = useState(initialFields)
  const [photos, setPhotos] = useState([])
  const [photoError, setPhotoError] = useState(null)
  const [fieldErrors, setFieldErrors] = useState({})
  const [serverError, setServerError] = useState(null)
  const [publishing, setPublishing] = useState(false)
  const [published, setPublished] = useState(false)
  const photosRef = useRef(photos)

  useEffect(() => {
    photosRef.current = photos
  }, [photos])

  useEffect(
    () => () => {
      for (const photo of photosRef.current) URL.revokeObjectURL(photo.url)
    },
    [],
  )

  function handleChange(event) {
    const { name, value } = event.target
    setFields((current) => ({ ...current, [name]: value }))
    setFieldErrors((current) => ({ ...current, [name]: undefined }))
    setServerError(null)
    setPublished(false)
  }

  function handlePhotoChange(event) {
    const selected = Array.from(event.target.files || [])
    const availableSlots = MAX_PHOTOS - photos.length
    const nextPhotos = []
    let error = null

    for (const file of selected.slice(0, availableSlots)) {
      if (!ACCEPTED_PHOTO_TYPES.has(file.type)) {
        error = 'Las fotografías deben estar en formato JPEG, PNG o WebP.'
        continue
      }
      if (file.size > MAX_PHOTO_SIZE) {
        error = 'Cada fotografía debe ocupar como máximo 5 MB.'
        continue
      }
      nextPhotos.push({ file, url: URL.createObjectURL(file) })
    }

    if (selected.length > availableSlots) {
      error = `Puedes añadir como máximo ${MAX_PHOTOS} fotografías.`
    }
    setPhotos((current) => [...current, ...nextPhotos])
    setPhotoError(error)
    setServerError(null)
    setPublished(false)
    event.target.value = ''
  }

  function removePhoto(index) {
    setPhotos((current) => {
      URL.revokeObjectURL(current[index].url)
      return current.filter((_, photoIndex) => photoIndex !== index)
    })
    setPhotoError(null)
    setServerError(null)
    setPublished(false)
  }

  async function handleSubmit(event) {
    event.preventDefault()
    if (publishing) return
    const errors = validateFields(fields)
    const photosError = validatePhotos(photos)
    setFieldErrors(errors)
    setPhotoError(photosError)
    setServerError(null)
    setPublished(false)

    if (Object.keys(errors).length > 0 || photosError) return

    setPublishing(true)
    try {
      const result = await publishProperty(fields, photos)
      if (result.ok && result.status === 201) {
        setPublished(true)
        return
      }
      if (result.status === 400) {
        const errorsByField = {}
        let nextPhotoError = null
        for (const [field, message] of Object.entries(result.data.errors || {})) {
          if (field.startsWith('photos')) nextPhotoError = message
          else if (FIELD_ALIASES[field]) errorsByField[FIELD_ALIASES[field]] = message
        }
        setFieldErrors(errorsByField)
        setPhotoError(nextPhotoError || result.data.error || null)
        if (!nextPhotoError && !Object.keys(errorsByField).length) {
          setServerError(result.data.error || 'Revisa los datos y las fotografías.')
        }
      } else if (result.status === 401) {
        setServerError(result.data.error || 'Necesitas iniciar sesión para publicar un inmueble.')
      } else if (result.status === 403) {
        setServerError(result.data.error || 'Tu cuenta no tiene permiso para publicar inmuebles.')
      } else {
        setServerError(result.data.error || 'No se pudo publicar el inmueble. Inténtalo de nuevo.')
      }
    } catch {
      setServerError('No se pudo conectar con el servidor. Comprueba tu conexión e inténtalo de nuevo.')
    } finally {
      setPublishing(false)
    }
  }

  return (
    <main className="publish-page">
      <header className="publish-page__header">
        <Logo size="sm" />
      </header>
      <div className="publish-page__inner">
        <button type="button" className="publish-page__back" onClick={() => navigate('/vendedor/inicio')}>
          ← Volver
        </button>
        <h1 className="publish-page__title">Publicar inmueble</h1>
        <p className="publish-page__subtitle">
          Completa los datos del alojamiento para crear tu anuncio.
        </p>

        <form className="publish-form" onSubmit={handleSubmit} noValidate>
          <FormField id="title" label="Título del anuncio" error={fieldErrors.title}>
            <input
              id="title"
              name="title"
              value={fields.title}
              onChange={handleChange}
              className={`form-field__input ${fieldErrors.title ? 'form-field__input--error' : ''}`}
              aria-invalid={!!fieldErrors.title}
            />
          </FormField>
          <FormField id="address" label="Calle y número" error={fieldErrors.address}>
            <input
              id="address"
              name="address"
              value={fields.address}
              onChange={handleChange}
              className={`form-field__input ${fieldErrors.address ? 'form-field__input--error' : ''}`}
              aria-invalid={!!fieldErrors.address}
            />
          </FormField>
          <div className="publish-form__grid">
            <FormField id="locality" label="Localidad" error={fieldErrors.locality}>
              <input
                id="locality"
                name="locality"
                value={fields.locality}
                onChange={handleChange}
                className={`form-field__input ${fieldErrors.locality ? 'form-field__input--error' : ''}`}
                aria-invalid={!!fieldErrors.locality}
              />
            </FormField>
            <FormField id="postalCode" label="Código postal" error={fieldErrors.postalCode}>
              <input
                id="postalCode"
                name="postalCode"
                value={fields.postalCode}
                onChange={handleChange}
                className={`form-field__input ${fieldErrors.postalCode ? 'form-field__input--error' : ''}`}
                aria-invalid={!!fieldErrors.postalCode}
              />
            </FormField>
          </div>
          <FormField id="description" label="Descripción" error={fieldErrors.description}>
            <textarea
              id="description"
              name="description"
              value={fields.description}
              onChange={handleChange}
              className={`form-field__input publish-form__textarea ${fieldErrors.description ? 'form-field__input--error' : ''}`}
              aria-invalid={!!fieldErrors.description}
            />
          </FormField>
          <div className="publish-form__grid publish-form__grid--three">
            <FormField id="price" label="Precio mensual (€)" error={fieldErrors.price}>
              <input id="price" name="price" type="number" min="0" step="0.01" value={fields.price} onChange={handleChange} className={`form-field__input ${fieldErrors.price ? 'form-field__input--error' : ''}`} aria-invalid={!!fieldErrors.price} />
            </FormField>
            <FormField id="area" label="Superficie (m²)" error={fieldErrors.area}>
              <input id="area" name="area" type="number" min="0" step="any" value={fields.area} onChange={handleChange} className={`form-field__input ${fieldErrors.area ? 'form-field__input--error' : ''}`} aria-invalid={!!fieldErrors.area} />
            </FormField>
            <FormField id="bedrooms" label="Dormitorios" error={fieldErrors.bedrooms}>
              <input id="bedrooms" name="bedrooms" type="number" min="0" step="1" value={fields.bedrooms} onChange={handleChange} className={`form-field__input ${fieldErrors.bedrooms ? 'form-field__input--error' : ''}`} aria-invalid={!!fieldErrors.bedrooms} />
            </FormField>
            <FormField id="bathrooms" label="Baños" error={fieldErrors.bathrooms}>
              <input id="bathrooms" name="bathrooms" type="number" min="1" step="1" value={fields.bathrooms} onChange={handleChange} className={`form-field__input ${fieldErrors.bathrooms ? 'form-field__input--error' : ''}`} aria-invalid={!!fieldErrors.bathrooms} />
            </FormField>
            <FormField id="tenants" label="Personas del alquiler" error={fieldErrors.tenants}>
              <input id="tenants" name="tenants" type="number" min="1" step="1" value={fields.tenants} onChange={handleChange} className={`form-field__input ${fieldErrors.tenants ? 'form-field__input--error' : ''}`} aria-invalid={!!fieldErrors.tenants} />
            </FormField>
            <FormField id="shared" label="¿Inmueble compartido?" error={fieldErrors.shared}>
              <select id="shared" name="shared" value={fields.shared} onChange={handleChange} className={`form-field__select ${fieldErrors.shared ? 'form-field__input--error' : ''}`} aria-invalid={!!fieldErrors.shared}>
                <option value="" disabled>Selecciona una opción</option>
                <option value="yes">Sí</option>
                <option value="no">No</option>
              </select>
            </FormField>
          </div>

          <fieldset className="publish-form__photos">
            <legend>Fotografías</legend>
            <p className="publish-form__hint">Añade entre 1 y 10 imágenes JPEG, PNG o WebP (máximo 5 MB cada una).</p>
            <label className="publish-form__file-button">
              Añadir fotografías
              <input type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={handlePhotoChange} />
            </label>
            {photos.length > 0 && (
              <div className="publish-form__photo-grid">
                {photos.map((photo, index) => (
                  <figure className="publish-form__photo" key={`${photo.file.name}-${photo.file.lastModified}-${index}`}>
                    <img src={photo.url} alt={`Fotografía ${index + 1}`} />
                    <button type="button" onClick={() => removePhoto(index)} aria-label={`Retirar fotografía ${index + 1}`}>
                      Retirar
                    </button>
                  </figure>
                ))}
              </div>
            )}
            {photoError && <p className="form-field__error" role="alert">{photoError}</p>}
          </fieldset>

          {serverError && <p className="publish-form__server-error" role="alert">{serverError}</p>}
          {published && <p className="publish-form__success" role="status">El anuncio se ha publicado correctamente.</p>}
          <button type="submit" className="publish-form__submit" disabled={publishing}>
            {publishing ? 'Publicando…' : published ? 'Publicado' : 'Publicar'}
          </button>
        </form>
      </div>
    </main>
  )
}
