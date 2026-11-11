import EstadoVacio from '../../../shared/components/EstadoVacio'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import ListaSucursales from '../components/ListaSucursales'

/** Sucursales de la empresa activa (el selector superior cambia de empresa). */
export default function SucursalesPage() {
  const { empresaActiva } = useEmpresas()
  const { tiene } = usePermisos()

  return (
    <main className="listado">
      {empresaActiva ? (
        <ListaSucursales
          key={empresaActiva.id}
          variante="pagina"
          empresaId={empresaActiva.id}
          empresaNombre={empresaActiva.razon_social}
          puedeEditar={tiene('SEGURIDAD.SUCURSALES.GESTIONAR')}
        />
      ) : (
        <EstadoVacio icono="building" titulo="No tiene una empresa activa" descripcion="Pida a un administrador que le dé acceso a una empresa." />
      )}
    </main>
  )
}
