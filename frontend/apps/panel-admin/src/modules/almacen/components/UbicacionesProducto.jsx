import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../../../core/api/client'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useOpciones } from '../hooks/useOpciones'

const ASIGNAR = 'INVENTARIO.UBICACIONES.ASIGNAR'

/**
 * Dónde está el producto en cada almacén de la empresa activa (una ubicación por almacén).
 * Cada cambio se guarda al elegirlo: no depende del botón «Guardar cambios» del producto.
 */
export default function UbicacionesProducto({ productoId }) {
  const { empresaActivaId } = useEmpresas()
  const { tiene } = usePermisos()
  const puedeAsignar = tiene(ASIGNAR)
  const activa = Boolean(empresaActivaId)

  const almacenes = useOpciones('/mantenimiento/almacenes/', { empresa: empresaActivaId }, { enabled: activa })
  const ubicaciones = useOpciones('/mantenimiento/ubicaciones/', { empresa: empresaActivaId }, { enabled: activa })
  const asignadas = useQuery({
    queryKey: ['ubicaciones-producto', empresaActivaId, productoId],
    queryFn: ({ signal }) =>
      api.get('/inventario/ubicaciones/', { params: { empresa: empresaActivaId, producto: productoId, page_size: 100 }, signal }).then((r) => r.data.results),
    enabled: activa,
  })

  const asignar = useMutacion({
    mutationFn: ({ almacen, ubicacion }) =>
      api.post('/inventario/ubicaciones/asignar/', { empresa: empresaActivaId, almacen, producto: productoId, ubicacion }),
    invalidar: [['ubicaciones-producto'], ['stock'], ['opciones', '/mantenimiento/ubicaciones/']],
    exito: 'Ubicación actualizada.',
  })

  const dondeEsta = new Map((asignadas.data ?? []).map((u) => [u.almacen, String(u.ubicacion)]))
  const porAlmacen = (almacenId) => (ubicaciones.data ?? []).filter((u) => u.almacen === almacenId)
  const cargando = almacenes.isLoading || ubicaciones.isLoading || asignadas.isLoading
  const fallo = almacenes.isError || ubicaciones.isError || asignadas.isError

  return (
    <PanelTarjeta id="ubicaciones" icono="ubicacion" titulo="Ubicación en el almacén" descripcion="Dónde encontrarlo en la empresa activa. Se guarda al elegir.">
      {!activa && <p className="celda-suave">Elija una empresa para ver o asignar ubicaciones.</p>}
      {activa && cargando && <p className="celda-suave">Cargando ubicaciones…</p>}
      {activa && fallo && <p role="alert" className="campo-error">No se pudieron cargar las ubicaciones. Recargue la página.</p>}
      {activa && !cargando && !fallo && (almacenes.data ?? []).length === 0 && (
        <p className="celda-suave">
          La empresa aún no tiene almacenes. <Link to="/mantenimiento/almacenes">Créalos aquí</Link>.
        </p>
      )}
      {activa && !cargando && !fallo && (almacenes.data ?? []).length > 0 && (
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Almacén</th>
                <th>Ubicación</th>
              </tr>
            </thead>
            <tbody>
              {almacenes.data.map((almacen) => {
                const opciones = porAlmacen(almacen.id)
                const valor = dondeEsta.get(almacen.id) ?? ''
                return (
                  <tr key={almacen.id}>
                    <td>
                      <strong>{almacen.nombre}</strong>
                      <small className="celda-suave"> · {almacen.codigo}</small>
                    </td>
                    <td>
                      <select
                        aria-label={`Ubicación en ${almacen.nombre}`}
                        value={valor}
                        disabled={!puedeAsignar || asignar.isPending || opciones.length === 0}
                        title={puedeAsignar ? undefined : 'No tiene permiso para cambiar ubicaciones'}
                        onChange={(e) => asignar.mutate({ almacen: almacen.id, ubicacion: e.target.value ? Number(e.target.value) : null })}
                      >
                        <option value="">{opciones.length === 0 ? 'Sin ubicaciones creadas' : 'Sin ubicación'}</option>
                        {opciones.map((u) => (
                          <option key={u.id} value={String(u.id)}>
                            {u.codigo} · {u.nombre}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="celda-suave precios-nota">
        Las ubicaciones se crean en <Link to="/mantenimiento/ubicaciones">Mantenimiento → Ubicaciones</Link>.
      </p>
    </PanelTarjeta>
  )
}
