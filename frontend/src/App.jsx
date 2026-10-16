import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './hooks/useAuth'
import { BuyerHome } from './pages/BuyerHome'
import { LandingPage } from './pages/LandingPage'
import { LoginPage } from './pages/LoginPage'
import { RegisterPage } from './pages/RegisterPage'
import { SellerHome } from './pages/SellerHome'

/**
 * Ruta protegida: redirige a '/' si no autenticado.
 * Redirige al inicio del rol correcto si el rol requerido no coincide.
 */
function PrivateRoute({ children, requiredRole }) {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div className="page-loading" aria-label="Cargando…">
        <div className="page-loading__spinner" aria-hidden="true" />
      </div>
    )
  }

  if (!user) return <Navigate to="/" replace />

  if (requiredRole && user.role !== requiredRole) {
    return (
      <Navigate
        to={user.role === 'SELLER' ? '/vendedor/inicio' : '/comprador/inicio'}
        replace
      />
    )
  }

  return children
}

export default function App() {
  return (
    <Routes>
      {/* Landing / página principal */}
      <Route path="/" element={<LandingPage />} />

      {/* Formulario de registro standalone (acceso directo por URL) */}
      <Route path="/registro" element={<RegisterPage />} />

      {/* Formulario de inicio de sesión */}
      <Route path="/login" element={<LoginPage />} />

      {/* Inicio Vendedor */}
      <Route
        path="/vendedor/inicio"
        element={
          <PrivateRoute requiredRole="SELLER">
            <SellerHome />
          </PrivateRoute>
        }
      />

      {/* Inicio Comprador */}
      <Route
        path="/comprador/inicio"
        element={
          <PrivateRoute requiredRole="BUYER">
            <BuyerHome />
          </PrivateRoute>
        }
      />

      {/* Cualquier ruta no definida → landing */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
