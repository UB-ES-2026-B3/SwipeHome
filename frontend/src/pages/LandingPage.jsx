import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Logo } from '../components/Logo'
import { RegisterForm } from '../components/RegisterForm'
import { useAuth } from '../hooks/useAuth'

/* ── Icono X ─────────────────────────────────────────────────────── */
function IconX() {
  return (
    <svg className="icon-x" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <line x1="2" y1="2" x2="14" y2="14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"/>
      <line x1="14" y1="2" x2="2"  y2="14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"/>
    </svg>
  )
}

/* ── Icono corazón (SVG de forma correcta) ───────────────────────── */
function IconHeart() {
  return (
    <svg className="icon-heart" viewBox="0 0 20 18" fill="currentColor" aria-hidden="true">
      <path d="M10 17C10 17 1 11.1 1 5.5C1 3.01 3.01 1 5.5 1C7.03 1 8.38 1.77 9.25 2.96L10 4L10.75 2.96C11.62 1.77 12.97 1 14.5 1C16.99 1 19 3.01 19 5.5C19 11.1 10 17 10 17Z" />
    </svg>
  )
}

/* ── Tarjetas de la baraja ───────────────────────────────────────── */
const CARDS = [
  { layer: 3, img: 'c', address: 'Calle Mayor 12',    name: 'Ático en Sol',    price: '1.200 €/mes' },
  { layer: 2, img: 'a', address: 'Gran Via 88',        name: 'Piso en Gràcia', price: '950 €/mes'   },
  { layer: 1, img: 'b', address: 'Passeig de Gràcia', name: 'Estudio moderno', price: '820 €/mes'   },
]

function CardDeck() {
  return (
    <div className="card-deck" aria-hidden="true">
      {CARDS.map((card) => (
        <div key={card.layer} className={`deck-card deck-card--${card.layer}`}>
          <div className={`deck-card__img deck-card__img--${card.img}`} />
          <div className="deck-card__body">
            <p className="deck-card__address">{card.address}</p>
            <p className="deck-card__name">{card.name}</p>
            <p className="deck-card__price">{card.price}</p>
          </div>
          {/* Acciones solo en la carta frontal */}
          {card.layer === 2 && (
            <div className="deck-card__actions">
              <button className="swipe-btn swipe-btn--pass" tabIndex={-1}>
                <IconX />
              </button>
              <button className="swipe-btn swipe-btn--like" tabIndex={-1}>
                <IconHeart />
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

/* ── Overlay de registro ─────────────────────────────────────────── */
function RegisterOverlay({ onClose }) {
  const panelRef = useRef(null)

  // Cerrar con Escape
  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  // Foco al panel al abrir
  useEffect(() => { panelRef.current?.focus() }, [])

  // Impedir scroll del body mientras está abierto
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  return (
    <div
      className="register-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Formulario de registro"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="register-panel"
        ref={panelRef}
        tabIndex={-1}
      >
        {/* Tirador */}
        <div className="register-panel__handle" aria-hidden="true" />

        <h2 className="register-panel__title">Crea tu cuenta</h2>
        <p className="register-panel__subtitle">
          Únete a SwipeHome. Es gratis.
        </p>

        <RegisterForm onSuccess={onClose} />

        <p className="register-form__login-link">
          ¿Ya tienes cuenta?{' '}
          <a href="/login">Inicia sesión</a>
        </p>
      </div>
    </div>
  )
}

/* ── Página principal ────────────────────────────────────────────── */
export function LandingPage() {
  const { user, loading } = useAuth()
  const navigate = useNavigate()
  const [showRegister, setShowRegister] = useState(false)

  // Si ya está autenticado, redirigir directamente
  useEffect(() => {
    if (!loading && user) {
      navigate(user.role === 'SELLER' ? '/vendedor/inicio' : '/comprador/inicio', { replace: true })
    }
  }, [user, loading, navigate])

  if (loading) {
    return (
      <div className="page-loading" aria-label="Cargando…">
        <div className="page-loading__spinner" aria-hidden="true" />
      </div>
    )
  }

  return (
    <div className="landing">
      {/* ── Navbar ─────────────────────────────────────────────── */}
      <header className="navbar">
        <Logo />
        <button
          className="navbar__login btn btn--red"
          onClick={() => navigate('/login')}
        >
          Iniciar sesión
        </button>
      </header>

      {/* ── Hero ───────────────────────────────────────────────── */}
      <main className="hero">
        <p className="hero__eyebrow">Alquiler de pisos</p>
        <h1 className="hero__title">
          Encuentra tu<br />
          próximo <em>hogar</em>
        </h1>
        <p className="hero__subtitle">
          Swipea entre cientos de pisos y habitaciones.
          Conectamos a personas con su próximo hogar.
        </p>

        {/* Botones CTA */}
        <div className="cta-group">
          <button
            className="btn btn--ghost"
            onClick={() => navigate('/login')}
          >
            Empezar
          </button>
          <button
            className="btn btn--dark"
            onClick={() => setShowRegister(true)}
          >
            Registrarse
          </button>
        </div>

        {/* Baraja de tarjetas */}
        <CardDeck />
      </main>

      {/* ── Overlay de registro ─────────────────────────────────── */}
      {showRegister && (
        <RegisterOverlay onClose={() => setShowRegister(false)} />
      )}
    </div>
  )
}
