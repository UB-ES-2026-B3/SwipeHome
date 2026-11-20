import { useState } from 'react'

export function PropertyPrice({ value, monthly = false }) {
  const amount = Number(value)
  const formatted = Number.isFinite(amount)
    ? amount.toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : value
  return <>{formatted} €{monthly && '/mes'}</>
}

export function PropertyGallery({ property, coverOnly = false }) {
  const [index, setIndex] = useState(0)
  const photos = property.photos || []

  return (
    <div className="property-card__gallery">
      {photos.length > 0 ? (
        <img src={photos[index]} alt={`${property.title}, fotografía ${index + 1}`} />
      ) : (
        <div className="property-card__no-photo">Sin fotografías</div>
      )}
      {!coverOnly && photos.length > 1 && (
        <>
          <button type="button" className="property-card__gallery-control property-card__gallery-control--prev"
            onClick={() => setIndex(index - 1)} disabled={index === 0} aria-label="Fotografía anterior">‹</button>
          <button type="button" className="property-card__gallery-control property-card__gallery-control--next"
            onClick={() => setIndex(index + 1)} disabled={index === photos.length - 1} aria-label="Fotografía siguiente">›</button>
          <span className="property-card__counter" aria-live="polite">{index + 1} de {photos.length}</span>
        </>
      )}
    </div>
  )
}

export function PropertyDetails({ property, monthly = false }) {
  return (
    <>
      <p className="property-card__location">{property.street}, {property.postal_code} · {property.city}</p>
      <p className="property-card__description">{property.description}</p>
      <dl className="property-card__details">
        <div><dt>Precio</dt><dd><PropertyPrice value={property.price} monthly={monthly} /></dd></div>
        <div><dt>Superficie</dt><dd>{property.surface} m²</dd></div>
        <div><dt>Dormitorios</dt><dd>{property.bedrooms}</dd></div>
        <div><dt>Baños</dt><dd>{property.bathrooms}</dd></div>
        <div><dt>Personas</dt><dd>{property.people}</dd></div>
        <div><dt>Compartido</dt><dd>{property.shared_accommodation ? 'Sí' : 'No'}</dd></div>
      </dl>
    </>
  )
}