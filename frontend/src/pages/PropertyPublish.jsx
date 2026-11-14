import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { publishProperty } from '../api/properties'
import { FormField } from '../components/FormField'
import {
  validatePhotoContent,
  validatePhotoSelection,
  validatePropertyFields,
} from './propertyForm'

const INITIAL_VALUES = {
  title: '',
  street: '',
  city: '',
  postal_code: '',
  description: '',
  price: '',
  surface: '',
  bedrooms: '',
  bathrooms: '',
  people: '',
  shared_accommodation: '',
}

const FIELDS = [
  ['title', 'Título', 'text'],
  ['street', 'Dirección', 'text'],
  ['city', 'Localidad', 'text'],
  ['postal_code', 'Código postal', 'text'],
  ['description', 'Descripción', 'textarea'],
  ['price', 'Precio mensual (€)', 'number'],
  ['surface', 'Superficie (m²)', 'number'],
  ['bedrooms', 'Dormitorios', 'number'],
  ['bathrooms', 'Baños', 'number'],
  ['people', 'Personas', 'number'],
]

function serverErrorMessage(status) {
  if (status === 401 || status === 403) {
    return 'Tu sesión no tiene permiso para publicar. Inicia sesión de nuevo como vendedor.'
  }
  if (status === 400) {
    return 'El servidor ha rechazado los datos. Revísalos e inténtalo de nuevo.'
  }
  return 'No se pudo publicar el inmueble. Comprueba tu conexión e inténtalo de nuevo.'
}

export function PropertyPublish() {
  const navigate = useNavigate()
  const [values, setValues] = useState(INITIAL_VALUES)
  const [photos, setPhotos] = useState([])
  const [photoErrors, setPhotoErrors] = useState([])
  const [processingPhotos, setProcessingPhotos] = useState(false)
  const [fieldErrors, setFieldErrors] = useState({})
  const [submitError, setSubmitError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [published, setPublished] = useState(false)
  const submittingRef = useRef(false)
  const processingPhotosRef = useRef(false)
  const photosRef = useRef(photos)

  useEffect(() => {
    photosRef.current = photos
  }, [photos])

  useEffect(
    () => () => photosRef.current.forEach(({ preview }) => URL.revokeObjectURL(preview)),
    [],
  )

  function updateField(event) {
    const { name, value } = event.target
    setValues((current) => ({ ...current, [name]: value }))
    setFieldErrors((current) => {
      const next = { ...current }
      delete next[name]
      return next
    })
  }

  async function addPhotos(event) {
    const files = Array.from(event.target.files ?? [])
    event.target.value = ''
    if (processingPhotosRef.current || files.length === 0) return

    processingPhotosRef.current = true
    setProcessingPhotos(true)
    try {
      const selection = validatePhotoSelection(files, photosRef.current.length)
      const inspected = await Promise.all(
        selection.accepted.map(async (file) => {
          try {
            return (await validatePhotoContent(file))
              ? { file }
              : { file, reason: 'El contenido del archivo no es una imagen JPEG, PNG o WebP válida.' }
          } catch {
            return { file, reason: 'No se pudo leer el contenido de la imagen.' }
          }
        }),
      )
      const accepted = inspected
        .filter(({ reason }) => !reason)
        .map(({ file }) => ({
          id: `${Date.now()}-${Math.random()}`,
          file,
          preview: URL.createObjectURL(file),
        }))
      const contentErrors = inspected
        .filter(({ reason }) => reason)
        .map(({ file, reason }) => ({ name: file.name, reason }))

      setPhotos((current) => [...current, ...accepted])
      setPhotoErrors([...selection.rejected, ...contentErrors])
      setFieldErrors((current) => {
        const next = { ...current }
        delete next.photos
        return next
      })
    } finally {
      processingPhotosRef.current = false
      setProcessingPhotos(false)
    }
  }

  function removePhoto(id) {
    const photo = photos.find((item) => item.id === id)
    if (photo) URL.revokeObjectURL(photo.preview)
    setPhotos((current) => current.filter((item) => item.id !== id))
  }

  async function submit(event) {
    event.preventDefault()
    if (submittingRef.current) return

    const validationErrors = validatePropertyFields(values)
    if (photos.length === 0) validationErrors.photos = 'Añade al menos una fotografía válida.'
    setFieldErrors(validationErrors)
    setSubmitError('')
    if (Object.keys(validationErrors).length > 0) return

    submittingRef.current = true
    setSubmitting(true)
    try {
      const result = await publishProperty(values, photos.map(({ file }) => file))
      if (!result.ok) {
        setSubmitError(serverErrorMessage(result.status))
        return
      }
      setPublished(true)
    } catch {
      setSubmitError('No se pudo conectar con el servidor. Tus datos y fotografías se conservan; inténtalo de nuevo.')
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  function startAnotherListing() {
    photos.forEach(({ preview }) => URL.revokeObjectURL(preview))
    setPhotos([])
    setValues(INITIAL_VALUES)
    setFieldErrors({})
    setPhotoErrors([])
    setSubmitError('')
    setPublished(false)
  }

  return (
    <main className="property-page">
      <header className="property-page__header">
        <button
          type="button"
          className="property-page__back"
          onClick={() => navigate('/vendedor/inicio')}
        >
          Volver al inicio
        </button>
        <h1 className="property-page__title">Publicar inmueble</h1>
        <p className="property-page__subtitle">Completa los datos y añade fotografías del inmueble.</p>
      </header>

      {published ? (
        <section className="property-success" role="status" aria-live="polite">
          <h2>¡Inmueble publicado!</h2>
          <p>Tu publicación se ha enviado correctamente.</p>
          <button type="button" className="register-form__submit" onClick={startAnotherListing}>
            Publicar otro inmueble
          </button>
          <button type="button" className="home-page__logout" onClick={() => navigate('/vendedor/inicio')}>
            Volver al inicio
          </button>
        </section>
      ) : (
        <form className="property-form" onSubmit={submit} noValidate>
          <section className="property-form__fields" aria-label="Datos del inmueble">
            {FIELDS.map(([name, label, type]) => (
              <FormField
                key={name}
                id={`property-${name}`}
                label={label}
                name={name}
                type={type === 'number' ? 'text' : undefined}
                inputMode={type === 'number' ? 'decimal' : undefined}
                value={values[name]}
                onChange={updateField}
                error={fieldErrors[name]}
                autoComplete="off"
              >
                {type === 'textarea' ? (
                  <textarea
                    id={`property-${name}`}
                    name={name}
                    className={`form-field__input property-form__textarea ${fieldErrors[name] ? 'form-field__input--error' : ''}`}
                    value={values[name]}
                    onChange={updateField}
                    aria-invalid={!!fieldErrors[name]}
                    aria-describedby={fieldErrors[name] ? `property-${name}-error` : undefined}
                    rows="4"
                  />
                ) : null}
              </FormField>
            ))}

            <FormField
              id="property-shared_accommodation"
              label="Alojamiento compartido"
              error={fieldErrors.shared_accommodation}
            >
              <select
                id="property-shared_accommodation"
                name="shared_accommodation"
                className="form-field__input form-field__select"
                value={values.shared_accommodation}
                onChange={updateField}
                aria-invalid={!!fieldErrors.shared_accommodation}
              >
                <option value="" disabled>Selecciona una opción</option>
                <option value="Sí">Sí</option>
                <option value="No">No</option>
              </select>
            </FormField>
          </section>

          <section className="property-photos" aria-labelledby="property-photos-title">
            <div className="property-photos__heading">
              <h2 id="property-photos-title">Fotografías</h2>
              <p>JPEG, PNG o WebP · máximo 5 MB cada una · hasta 10 fotografías.</p>
            </div>
            <label className="property-photos__picker" htmlFor="property-photos-input">
              Seleccionar fotografías
            </label>
            <input
              id="property-photos-input"
              className="property-photos__input"
              type="file"
              accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
              multiple
              onChange={addPhotos}
              disabled={submitting || processingPhotos}
            />
            {processingPhotos && <p role="status">Comprobando fotografías…</p>}
            {fieldErrors.photos && <p className="form-field__error" role="alert">{fieldErrors.photos}</p>}
            {photoErrors.length > 0 && (
              <ul className="property-photos__errors" role="alert" aria-live="polite">
                {photoErrors.map((error, index) => (
                  <li key={`${error.name}-${index}`}><strong>{error.name}:</strong> {error.reason}</li>
                ))}
              </ul>
            )}
            {photos.length > 0 && (
              <ul className="property-photos__grid" aria-label="Fotografías seleccionadas">
                {photos.map((photo, index) => (
                  <li className="property-photos__item" key={photo.id}>
                    <img src={photo.preview} alt={`Vista previa de la fotografía ${index + 1}`} />
                    <button
                      type="button"
                      className="property-photos__remove"
                      onClick={() => removePhoto(photo.id)}
                      disabled={submitting || processingPhotos}
                      aria-label={`Retirar fotografía ${index + 1}`}
                    >
                      Retirar
                    </button>
                    <span>Fotografía {index + 1}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {submitError && <p className="register-form__server-error" role="alert">{submitError}</p>}
          <button
            type="submit"
            className="register-form__submit"
            disabled={submitting || processingPhotos}
          >
            {submitting ? 'Publicando…' : processingPhotos ? 'Comprobando fotografías…' : 'Publicar inmueble'}
          </button>
        </form>
      )}
    </main>
  )
}
