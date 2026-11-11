import { usePermisos } from '../contexts/PermisosContext'

/**
 * Muestra a sus hijos solo si el usuario tiene el permiso (oculta botones y secciones).
 * Es una comodidad de interfaz: el backend vuelve a verificar toda operación.
 *
 *   <Can permiso="VENTAS.ANULAR"><button>Anular</button></Can>
 *   <Can permiso="MANTENIMIENTO.CLIENTES.VER" organizacion fallback={<p>Sin acceso</p>}>…</Can>
 */
export default function Can({ permiso, organizacion = false, alcanceMinimo, fallback = null, children }) {
  const { tiene } = usePermisos()
  return tiene(permiso, { organizacion, alcanceMinimo }) ? children : fallback
}
