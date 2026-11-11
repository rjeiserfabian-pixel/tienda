import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

/** Protege rutas del panel. La autorización real sigue siendo del backend. */
export default function RequireAuth() {
  const { autenticado, cargando, usuario } = useAuth()
  const ubicacion = useLocation()

  if (cargando) return <p style={{ padding: 24 }}>Cargando…</p>
  if (!autenticado) return <Navigate to="/login" replace state={{ desde: ubicacion }} />
  // Clave temporal: hasta cambiarla solo se puede acceder a la pantalla de cambio.
  if (usuario.debe_cambiar_password && ubicacion.pathname !== '/cuenta/password') {
    return <Navigate to="/cuenta/password" replace />
  }
  // Política de la organización: sin segundo factor activo solo se puede configurarlo.
  if (usuario.debe_configurar_mfa && ubicacion.pathname !== '/cuenta/seguridad') {
    return <Navigate to="/cuenta/seguridad" replace />
  }
  return <Outlet />
}
