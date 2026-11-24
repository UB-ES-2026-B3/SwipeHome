import { Link, useLocation } from 'react-router-dom'
import { Logo } from './Logo'
import { useAuth } from '../hooks/useAuth'

const buyerLinks = [
  { to: '/comprador/matches', label: 'Mis matches' },
  { to: '/notificaciones', label: 'Notificaciones' },
  { to: '/mi-perfil', label: 'Mi perfil' },
]

const sellerLinks = [
  { to: '/notificaciones', label: 'Notificaciones' },
  { to: '/mi-perfil', label: 'Mi perfil' },
]

export function DashboardHeader() {
  const { user, logout } = useAuth()
  const { pathname } = useLocation()
  const isSeller = user.role === 'SELLER'
  const homePath = isSeller ? '/vendedor/inicio' : '/comprador/inicio'
  const links = isSeller ? sellerLinks : buyerLinks
  const accountClass = isSeller ? 'seller-dashboard' : 'buyer-dashboard'

  return (
    <header className="home-page__header dashboard-header">
      <Logo size="sm" to={homePath} />
      <nav className="dashboard-header__navigation" aria-label="Navegación principal">
        {links.filter(({ to }) => to !== pathname).map(({ to, label }) => (
          <Link className="btn btn--ghost uniform-action dashboard-header__link" key={to} to={to}>
            {label}
          </Link>
        ))}
      </nav>
      <div className={`dashboard-header__account ${accountClass}__account`}>
        <span className={`${accountClass}__role uniform-action`}>
          {isSeller ? 'Vendedor' : 'Comprador'}
        </span>
        <button
          type="button"
          className={`${accountClass}__logout uniform-action`}
          onClick={logout}
        >
          Cerrar sesión
        </button>
      </div>
    </header>
  )
}
