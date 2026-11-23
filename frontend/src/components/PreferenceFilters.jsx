import { useCallback, useEffect, useRef, useState } from 'react'
import { getBuyerFilters, saveBuyerFilters } from '../api/properties'

const EMPTY_FILTERS = {
  price_min: null,
  price_max: null,
  surface_min: null,
  surface_max: null,
  bedrooms_min: null,
  bathrooms_min: null,
  people_min: null,
  shared_accommodation: null,
}

const DECIMAL_FIELDS = ['price_min', 'price_max', 'surface_min', 'surface_max']
const INTEGER_FIELDS = ['bedrooms_min', 'bathrooms_min', 'people_min']

function toDraft(filters) {
  return {
    ...filters,
    price_min: filters.price_min ?? '',
    price_max: filters.price_max ?? '',
    surface_min: filters.surface_min ?? '',
    surface_max: filters.surface_max ?? '',
    bedrooms_min: filters.bedrooms_min ?? '',
    bathrooms_min: filters.bathrooms_min ?? '',
    people_min: filters.people_min ?? '',
    shared_accommodation: filters.shared_accommodation == null
      ? ''
      : String(filters.shared_accommodation),
  }
}

function validateDraft(draft) {
  const errors = {}
  for (const field of DECIMAL_FIELDS) {
    if (draft[field] === '') continue
    const decimalMatch = /^(\d+)(?:\.(\d{1,2}))?$/.exec(draft[field])
    if (!decimalMatch || decimalMatch[1].length + (decimalMatch[2]?.length || 0) > 10) {
      errors[field] = 'Usa un número no negativo con hasta dos decimales.'
    }
  }
  for (const field of INTEGER_FIELDS) {
    if (draft[field] === '') continue
    if (!/^\d{1,9}$/.test(draft[field])) {
      errors[field] = 'Introduce un número entero no negativo.'
    }
  }
  if (
    !errors.price_min && !errors.price_max &&
    draft.price_min !== '' && draft.price_max !== '' &&
    Number(draft.price_min) > Number(draft.price_max)
  ) {
    errors.price_min = 'El mínimo no puede superar el máximo.'
    errors.price_max = 'El máximo debe ser igual o mayor que el mínimo.'
  }
  if (
    !errors.surface_min && !errors.surface_max &&
    draft.surface_min !== '' && draft.surface_max !== '' &&
    Number(draft.surface_min) > Number(draft.surface_max)
  ) {
    errors.surface_min = 'El mínimo no puede superar el máximo.'
    errors.surface_max = 'El máximo debe ser igual o mayor que el mínimo.'
  }
  return errors
}

function toPayload(draft) {
  const payload = { ...draft }
  for (const field of DECIMAL_FIELDS) {
    payload[field] = draft[field] === '' ? null : draft[field]
  }
  for (const field of INTEGER_FIELDS) {
    payload[field] = draft[field] === '' ? null : Number(draft[field])
  }
  payload.shared_accommodation = draft.shared_accommodation === ''
    ? null
    : draft.shared_accommodation === 'true'
  return payload
}

function apiError(result, fallback) {
  return result.data?.error || fallback
}

export function PreferenceFilters({ onApplied, onBusyChange, disabled = false }) {
  const [filters, setFilters] = useState(toDraft(EMPTY_FILTERS))
  const [savedFilters, setSavedFilters] = useState(toDraft(EMPTY_FILTERS))
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState({})
  const [message, setMessage] = useState('')
  const [loadError, setLoadError] = useState('')
  const requestLock = useRef(false)
  const loadVersion = useRef(0)

  const loadFilters = useCallback(async (showLoading = true) => {
    const version = ++loadVersion.current
    if (showLoading) {
      setLoading(true)
      setLoadError('')
    }
    try {
      const result = await getBuyerFilters()
      if (version !== loadVersion.current) return
      if (!result.ok) {
        setLoadError(apiError(result, 'No se pudieron consultar tus filtros.'))
        return
      }
      const loaded = toDraft(result.data.filters)
      setSavedFilters(loaded)
      setFilters(loaded)
    } catch {
      if (version === loadVersion.current) {
        setLoadError('No hay conexión para consultar tus filtros. Inténtalo de nuevo.')
      }
    } finally {
      if (version === loadVersion.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadFilters(false)
    return () => {
      loadVersion.current += 1
    }
  }, [loadFilters])

  async function persistFilters(nextFilters, successMessage) {
    if (requestLock.current || loading || disabled) return
    requestLock.current = true
    setSaving(true)
    setErrors({})
    setMessage('')
    onBusyChange?.(true)
    let saved = false
    try {
      const result = await saveBuyerFilters(toPayload(nextFilters))
      if (!result.ok) {
        if (result.status === 400 && result.data?.errors) {
          setErrors(result.data.errors)
        } else {
          setMessage(apiError(result, 'No se pudieron guardar los filtros.'))
        }
        return
      }
      saved = true
      const updated = toDraft(result.data.filters)
      setSavedFilters(updated)
      setFilters(updated)
      let refreshed = true
      if (onApplied) refreshed = await onApplied()
      setMessage(refreshed === false
        ? 'Filtros guardados, pero no se pudieron cargar las viviendas. Puedes reintentar.'
        : successMessage)
    } catch {
      setMessage(saved
        ? 'Filtros guardados, pero no se pudieron cargar las viviendas. Puedes reintentar.'
        : 'No hay conexión para guardar tus filtros. Inténtalo de nuevo.')
    } finally {
      requestLock.current = false
      setSaving(false)
      onBusyChange?.(false)
    }
  }

  function handleSubmit(event) {
    event.preventDefault()
    const nextErrors = validateDraft(filters)
    setErrors(nextErrors)
    setMessage('')
    if (Object.keys(nextErrors).length) return
    persistFilters(filters, 'Filtros guardados y aplicados.')
  }

  function cancelChanges() {
    setFilters(savedFilters)
    setErrors({})
    setMessage('')
  }

  function resetFilters() {
    const defaults = toDraft(EMPTY_FILTERS)
    persistFilters(defaults, 'Filtros restablecidos; conservamos tus intereses y descartes.')
  }

  function updateField(event) {
    const { name, value } = event.target
    setFilters((current) => ({ ...current, [name]: value }))
    setErrors((current) => ({ ...current, [name]: undefined }))
    setMessage('')
  }

  function field(name, label, { min, step = '1' } = {}) {
    return (
      <label className="preference-filters__field" htmlFor={`filter-${name}`} key={name}>
        <span>{label}</span>
        <input
          id={`filter-${name}`}
          name={name}
          type="number"
          min={min ?? '0'}
          step={step}
          value={filters[name]}
          onChange={updateField}
          disabled={loading || saving || disabled}
          aria-invalid={Boolean(errors[name])}
          aria-describedby={errors[name] ? `filter-${name}-error` : undefined}
        />
        {errors[name] && (
          <span className="preference-filters__error" id={`filter-${name}-error`}>
            {errors[name]}
          </span>
        )}
      </label>
    )
  }

  return (
    <section className="profile-card preference-filters" aria-labelledby="preference-filters-title">
      <h2 id="preference-filters-title">Preferencias de viviendas</h2>
      <p>Deja un campo vacío para no limitar ese criterio.</p>
      {loadError ? (
        <div role="alert" className="preference-filters__notice preference-filters__notice--error">
          <p>{loadError}</p>
          <button type="button" className="btn btn--ghost" onClick={loadFilters} disabled={disabled}>Reintentar</button>
        </div>
      ) : loading ? (
        <p role="status">Cargando tus filtros…</p>
      ) : (
        <form onSubmit={handleSubmit} noValidate aria-busy={saving}>
          {message && <p className="preference-filters__notice" role="status">{message}</p>}
          <div className="preference-filters__grid">
            {field('price_min', 'Precio mínimo (€)', { step: '0.01' })}
            {field('price_max', 'Precio máximo (€)', { step: '0.01' })}
            {field('surface_min', 'Superficie mínima (m²)', { step: '0.01' })}
            {field('surface_max', 'Superficie máxima (m²)', { step: '0.01' })}
            {field('bedrooms_min', 'Dormitorios mínimos')}
            {field('bathrooms_min', 'Baños mínimos')}
            {field('people_min', 'Personas mínimas')}
            <label className="preference-filters__field" htmlFor="filter-shared_accommodation">
              <span>Alojamiento compartido</span>
              <select
                id="filter-shared_accommodation"
                name="shared_accommodation"
                value={filters.shared_accommodation}
                onChange={updateField}
                disabled={saving || disabled}
              >
                <option value="">Sin restricción</option>
                <option value="true">Sí</option>
                <option value="false">No</option>
              </select>
            </label>
          </div>
          <div className="preference-filters__actions">
            <button type="submit" className="btn btn--red" disabled={saving || disabled}>
              {saving ? 'Aplicando…' : 'Aplicar filtros'}
            </button>
            <button type="button" className="btn btn--ghost" onClick={cancelChanges} disabled={saving || disabled}>
              Cancelar cambios
            </button>
            <button type="button" className="btn btn--ghost" onClick={resetFilters} disabled={saving || disabled}>
              Restablecer filtros
            </button>
          </div>
          {Object.values(errors).some(Boolean) && (
            <p className="preference-filters__error" role="alert">
              Corrige los campos indicados antes de aplicar los filtros.
            </p>
          )}
        </form>
      )}
    </section>
  )
}
