import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './hooks/useAuth'
import { BuyerHome } from './pages/BuyerHome'
import { RegisterPage } from './pages/RegisterPage'
import { SellerHome } from './pages/SellerHome'

/**
 * Componente de ruta protegida.
 * Redirige a /registro si el usuario no está autenticado.
 * Muestra un spinner mientras se resuelve la sesión inicial.
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

  if (!user) {
    return <Navigate to="/registro" replace />
  }

  if (requiredRole && user.role !== requiredRole) {
    // Redirige al inicio correcto si el rol no coincide
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
      {/* Registro */}
      <Route path="/registro" element={<RegisterPage />} />

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

      {/* Raíz: redirige a registro (login se añadirá en US2) */}
      <Route path="/" element={<Navigate to="/registro" replace />} />

      {/* Cualquier ruta no definida */}
      <Route path="*" element={<Navigate to="/registro" replace />} />
    </Routes>
  )
}
