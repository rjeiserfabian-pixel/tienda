import { Outlet } from 'react-router-dom'
import { usePermisos } from '../../shared/contexts/PermisosContext'

/** Protege una rama de rutas por permiso. La autorización real sigue siendo del backend. */
export default function RequirePermiso({ permiso, organizacion = false }) {
  const { tiene, cargando } = usePermisos()

  if (cargando) return <p style={{ padding: 24 }}>Verificando permisos…</p>
  if (!tiene(permiso, { organizacion })) {
    return (
      <section role="alert" style={{ padding: 24 }}>
        <h2>Acceso no autorizado</h2>
        <p>No tiene permiso para ver esta sección en la empresa seleccionada.</p>
      </section>
    )
  }
  return <Outlet />
}
