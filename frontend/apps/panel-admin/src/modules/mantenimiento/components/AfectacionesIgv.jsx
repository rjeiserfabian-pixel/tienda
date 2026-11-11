import { useState } from 'react'
import { api } from '../../../core/api/client'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useListado } from '../../../shared/hooks/useListado'
import { useMutacion } from '../../../shared/hooks/useMutacion'

const GRUPOS = [
  ['GRAVADO', 'Gravado'],
  ['EXONERADO', 'Exonerado'],
  ['INAFECTO', 'Inafecto'],
  ['EXPORTACION', 'Exportación'],
]
const BASE = ['10', '20'] // sin ellas el sistema no puede proponer el IGV

function Casilla({ marcada, deshabilitada, titulo, etiqueta, onCambio }) {
  return (
    <input
      type="checkbox"
      checked={marcada}
      disabled={deshabilitada}
      title={titulo}
      aria-label={etiqueta}
      onChange={(e) => onCambio(e.target.checked)}
    />
  )
}

/** Catálogo 07 de SUNAT: no se crea ni se borra; se ajusta dónde se ofrece cada afectación. */
export default function AfectacionesIgv() {
  const { tiene } = usePermisos()
  const puedeEditar = tiene('MANTENIMIENTO.IGV.EDITAR', { organizacion: true })
  const [grupo, setGrupo] = useState('')
  const consulta = useListado(['afectaciones-igv'], '/mantenimiento/afectaciones-igv/', { grupo, page_size: 50 })
  const filas = consulta.data?.results ?? []

  const cambiar = useMutacion({
    mutationFn: ({ id, ...datos }) => api.patch(`/mantenimiento/afectaciones-igv/${id}/`, datos).then((r) => r.data),
    invalidar: [['afectaciones-igv'], ['opciones']],
    exito: 'Afectación actualizada.',
  })
  const ocupado = cambiar.isPending

  return (
    <PanelTarjeta
      id="afectaciones"
      icono="layers"
      titulo="Afectaciones del IGV"
      descripcion="Los tipos de operación de SUNAT (Catálogo 07). Elige cuáles se ofrecen al registrar una compra y cuáles al vender."
      acciones={
        <select className="boton-cabecera" aria-label="Filtrar por grupo" value={grupo} onChange={(e) => setGrupo(e.target.value)}>
          <option value="">Todos los grupos</option>
          {GRUPOS.map(([v, t]) => (
            <option key={v} value={v}>{t}</option>
          ))}
        </select>
      }
    >
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Código</th>
                <th>Afectación</th>
                <th>Impuesto</th>
                <th className="centrado">En compras</th>
                <th className="centrado">En ventas</th>
                <th className="centrado">Activa</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <tr><td colSpan={6} className="estado-vacio">No hay afectaciones en ese grupo.</td></tr>}
              {filas.map((a) => {
                const base = BASE.includes(a.codigo)
                const motivo = base ? 'Es la base del sistema: no se puede quitar' : undefined
                return (
                  <tr key={a.id} className={a.estado === 'INACTIVO' ? 'anulado' : undefined}>
                    <td><strong>{a.codigo}</strong></td>
                    <td>
                      {a.nombre}
                      {a.gratuita && <small className="celda-suave"> · gratuita</small>}
                    </td>
                    <td className="celda-suave">{a.impuesto_nombre}</td>
                    <td className="centrado">
                      <Casilla marcada={a.aplica_compras} deshabilitada={!puedeEditar || ocupado || base} titulo={motivo} etiqueta={`Ofrecer ${a.nombre} en compras`} onCambio={(v) => cambiar.mutate({ id: a.id, aplica_compras: v })} />
                    </td>
                    <td className="centrado">
                      <Casilla marcada={a.aplica_ventas} deshabilitada={!puedeEditar || ocupado || base} titulo={motivo} etiqueta={`Ofrecer ${a.nombre} en ventas`} onCambio={(v) => cambiar.mutate({ id: a.id, aplica_ventas: v })} />
                    </td>
                    <td className="centrado">
                      <Casilla marcada={a.estado === 'ACTIVO'} deshabilitada={!puedeEditar || ocupado || base} titulo={motivo} etiqueta={`${a.nombre} activa`} onCambio={(v) => cambiar.mutate({ id: a.id, estado: v ? 'ACTIVO' : 'INACTIVO' })} />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </EstadoConsulta>
    </PanelTarjeta>
  )
}
