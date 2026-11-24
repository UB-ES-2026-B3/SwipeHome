import { useEffect, useRef, useState } from 'react'
import { getFilterOptions, getSearchPreferences, resetSearchPreferences, saveSearchPreferences } from '../api/properties'
import { FormField } from './FormField'

const EMPTY = {
  city: null, postal_code: null, min_price: null, max_price: null,
  min_area: null, max_area: null, bedrooms: null, min_bathrooms: null,
  people_offered: null, is_shared: null,
}

function draftFrom(values) {
  return Object.fromEntries(Object.keys(EMPTY).map((key) => [
    key,
    values?.[key] == null ? '' : String(values[key]),
  ]))
}

function payloadFrom(draft) {
  const payload = {}
  for (const [key, value] of Object.entries(draft)) {
    if (value === '') payload[key] = null
    else if (['bedrooms', 'min_bathrooms', 'people_offered'].includes(key)) payload[key] = Number(value)
    else if (key === 'is_shared') payload[key] = value === 'true'
    else payload[key] = value
  }
  return payload
}

function validateDraft(draft) {
  const errors = {}
  for (const key of ['min_price', 'max_price', 'min_area', 'max_area']) {
    if (draft[key] !== '' && !/^\d+(?:\.\d{1,2})?$/.test(draft[key])) {
      errors[key] = 'Introduce una cantidad válida con hasta dos decimales.'
    }
  }
  if (!errors.min_price && !errors.max_price && draft.min_price && draft.max_price &&
      Number(draft.min_price) > Number(draft.max_price)) {
    errors.max_price = 'Debe ser mayor o igual al precio mínimo.'
  }
  if (!errors.min_area && !errors.max_area && draft.min_area && draft.max_area &&
      Number(draft.min_area) > Number(draft.max_area)) {
    errors.max_area = 'Debe ser mayor o igual a la superficie mínima.'
  }
  return errors
}

export function SearchPreferencesForm({ onCancel, onSaved, onReset, inModal = false }) {
  const [saved, setSaved] = useState(EMPTY)
  const [draft, setDraft] = useState(draftFrom(EMPTY))
  const [cities, setCities] = useState([])
  const [errors, setErrors] = useState({})
  const [status, setStatus] = useState('loading')
  const [message, setMessage] = useState('')
  const saving = useRef(false)

  useEffect(() => {
    if (!inModal) return undefined
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onCancel?.()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [inModal, onCancel])

  useEffect(() => {
    const task = window.setTimeout(async () => {
      const [preferencesResult, optionsResult] = await Promise.all([getSearchPreferences(), getFilterOptions()])
      if (!preferencesResult.ok || !optionsResult.ok) {
        setMessage(preferencesResult.data?.error || optionsResult.data?.error || 'No se pudieron cargar las preferencias.')
        setStatus('error')
        return
      }
      const values = { ...EMPTY, ...preferencesResult.data }
      setSaved(values)
      setDraft(draftFrom(values))
      setCities(optionsResult.data.cities || [])
      setStatus('ready')
    }, 0)
    return () => window.clearTimeout(task)
  }, [])

  function update(field, value) {
    setDraft((current) => ({ ...current, [field]: value }))
    setErrors((current) => ({ ...current, [field]: undefined }))
    setMessage('')
  }

  function cancel() {
    setDraft(draftFrom(saved))
    setErrors({})
    setMessage('')
    onCancel?.()
  }

  async function apply(event) {
    event.preventDefault()
    if (saving.current) return
    const validation = validateDraft(draft)
    setErrors(validation)
    setMessage('')
    if (Object.keys(validation).length) return
    saving.current = true
    setStatus('saving')
    try {
      const result = await saveSearchPreferences(payloadFrom(draft))
      if (!result.ok) {
        setErrors(result.data?.errors || {})
        setMessage(result.data?.error || 'No se pudieron guardar las preferencias.')
        setStatus('ready')
        return
      }
      const values = { ...EMPTY, ...result.data }
      setSaved(values)
      setDraft(draftFrom(values))
      setStatus('ready')
      setMessage('Preferencias aplicadas.')
      onSaved?.(values)
    } catch {
      setStatus('ready')
      setMessage('No hay conexión con el servidor. Inténtalo de nuevo.')
    } finally {
      saving.current = false
    }
  }

  async function reset() {
    if (saving.current) return
    saving.current = true
    setStatus('saving')
    setErrors({})
    setMessage('')
    try {
      const result = await resetSearchPreferences()
      if (!result.ok) {
        setMessage(result.data?.error || 'No se pudieron restablecer las preferencias.')
        setStatus('ready')
        return
      }
      setSaved(EMPTY)
      setDraft(draftFrom(EMPTY))
      setStatus('ready')
      setMessage('Filtros restablecidos.')
      onReset?.()
    } catch {
      setStatus('ready')
      setMessage('No hay conexión con el servidor. Inténtalo de nuevo.')
    } finally {
      saving.current = false
    }
  }

  return (
    <div className={inModal ? 'preferences-modal__dialog' : 'preferences-form'} role={inModal ? 'dialog' : undefined}
      aria-modal={inModal ? 'true' : undefined} aria-labelledby="search-preferences-title">
      <h2 id="search-preferences-title">Preferencias de búsqueda</h2>
      {status === 'loading' && <p>Cargando preferencias…</p>}
      {status === 'error' && <p role="alert">{message}</p>}
      {status !== 'loading' && status !== 'error' && (
        <form onSubmit={apply} noValidate>
          {message && <p className={Object.values(errors).some(Boolean) ? 'preferences-form__error' : 'preferences-form__success'} role="status">{message}</p>}
          <div className="preferences-form__grid">
            <FormField id="pref-city" label="Localidad" error={errors.city}>
              <select id="pref-city" className={`form-field__input ${errors.city ? 'form-field__input--error' : ''}`}
                value={draft.city} onChange={(event) => update('city', event.target.value)} aria-invalid={!!errors.city}>
                <option value="">Cualquiera</option>
                {cities.map((city) => <option key={city} value={city}>{city}</option>)}
              </select>
            </FormField>
            <FormField id="pref-postal-code" label="Código postal" error={errors.postal_code}>
              <input id="pref-postal-code" className={`form-field__input ${errors.postal_code ? 'form-field__input--error' : ''}`}
                value={draft.postal_code} onChange={(event) => update('postal_code', event.target.value)} placeholder="Cualquiera" />
            </FormField>
            <FormField id="pref-min-price" label="Precio mínimo (€)" error={errors.min_price}>
              <input id="pref-min-price" className={`form-field__input ${errors.min_price ? 'form-field__input--error' : ''}`}
                inputMode="decimal" value={draft.min_price} onChange={(event) => update('min_price', event.target.value)} placeholder="Sin mínimo" />
            </FormField>
            <FormField id="pref-max-price" label="Precio máximo (€)" error={errors.max_price}>
              <input id="pref-max-price" className={`form-field__input ${errors.max_price ? 'form-field__input--error' : ''}`}
                inputMode="decimal" value={draft.max_price} onChange={(event) => update('max_price', event.target.value)} placeholder="Sin máximo" />
            </FormField>
            <FormField id="pref-min-area" label="Superficie mínima (m²)" error={errors.min_area}>
              <input id="pref-min-area" className={`form-field__input ${errors.min_area ? 'form-field__input--error' : ''}`}
                inputMode="decimal" value={draft.min_area} onChange={(event) => update('min_area', event.target.value)} placeholder="Sin mínimo" />
            </FormField>
            <FormField id="pref-max-area" label="Superficie máxima (m²)" error={errors.max_area}>
              <input id="pref-max-area" className={`form-field__input ${errors.max_area ? 'form-field__input--error' : ''}`}
                inputMode="decimal" value={draft.max_area} onChange={(event) => update('max_area', event.target.value)} placeholder="Sin máximo" />
            </FormField>
            <FormField id="pref-bedrooms" label="Dormitorios" error={errors.bedrooms}>
              <select id="pref-bedrooms" className={`form-field__input ${errors.bedrooms ? 'form-field__input--error' : ''}`}
                value={draft.bedrooms} onChange={(event) => update('bedrooms', event.target.value)}>
                <option value="">Cualquiera</option>
                {Array.from({ length: 11 }, (_, value) => <option key={value} value={String(value)}>{value === 0 ? '0 — Estudio' : String(value)}</option>)}
              </select>
            </FormField>
            <FormField id="pref-min-bathrooms" label="Baños mínimos" error={errors.min_bathrooms}>
              <select id="pref-min-bathrooms" className={`form-field__input ${errors.min_bathrooms ? 'form-field__input--error' : ''}`}
                value={draft.min_bathrooms} onChange={(event) => update('min_bathrooms', event.target.value)}>
                <option value="">Cualquiera</option>
                {Array.from({ length: 10 }, (_, index) => <option key={index + 1} value={String(index + 1)}>{index + 1}</option>)}
              </select>
            </FormField>
            <FormField id="pref-people" label="Personas" error={errors.people_offered}>
              <select id="pref-people" className={`form-field__input ${errors.people_offered ? 'form-field__input--error' : ''}`}
                value={draft.people_offered} onChange={(event) => update('people_offered', event.target.value)}>
                <option value="">Cualquiera</option>
                {Array.from({ length: 10 }, (_, index) => <option key={index + 1} value={String(index + 1)}>{index + 1}</option>)}
              </select>
            </FormField>
            <FormField id="pref-is-shared" label="Alojamiento compartido" error={errors.is_shared}>
              <select id="pref-is-shared" className={`form-field__input ${errors.is_shared ? 'form-field__input--error' : ''}`}
                value={draft.is_shared} onChange={(event) => update('is_shared', event.target.value)}>
                <option value="">Sin preferencia</option>
                <option value="true">Sí</option>
                <option value="false">No</option>
              </select>
            </FormField>
          </div>
          <div className="preferences-form__actions">
            <button type="submit" className="btn btn--red" disabled={status === 'saving'}>Aplicar filtros</button>
            <button type="button" className="btn btn--ghost" onClick={cancel} disabled={status === 'saving'}>Cancelar</button>
            <button type="button" className="btn btn--ghost" onClick={reset} disabled={status === 'saving'}>Restablecer filtros</button>
          </div>
        </form>
      )}
    </div>
  )
}
