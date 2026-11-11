import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import { api, mensajeDeError } from '../../../core/api/client'
import BotonVolver from '../../../shared/components/BotonVolver'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Can from '../../../shared/components/Can'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { fechaCorta } from '../../almacen/inventario'
import { useImpresionDocumento } from '../../ventas/hooks/useImpresionDocumento'
import AdelantosOrden from '../components/AdelantosOrden'
import AsignarTecnicoModal from '../components/AsignarTecnicoModal'
import AvisosOrden from '../components/AvisosOrden'
import DiagnosticoOrden from '../components/DiagnosticoOrden'
import EntregaGarantiaOrden from '../components/EntregaGarantiaOrden'
import PanelEstado from '../components/PanelEstado'
import PresupuestoOrden from '../components/PresupuestoOrden'
import { especificacionIngreso } from '../especificaciones'
import { ESTADOS_ORDEN, fechaHora } from '../servicio'
import '../../almacen/inventario.css'
import '../../compras/compras.css'
import '../servicio-tecnico.css'

const RUTA = '/servicio-tecnico/ordenes'

function Dato({ titulo, children }) {
  return (
    <div className="gasto-dato">
      <dt>{titulo}</dt>
      <dd>{children}</dd>
    </div>
  )
}

/** La clave o patrón del equipo: se pide al servidor solo al pulsar, y cada consulta queda en la auditoría. */
function ClaveEquipo({ id }) {
  const [clave, setClave] = useState(null)
  const [cargando, setCargando] = useState(false)
  const [error, setError] = useState('')
  const pedir = async () => {
    if (cargando) return
    setCargando(true)
    setError('')
    try {
      const respuesta = await api.get(`/servicio-tecnico/ordenes/${id}/clave/`)
      setClave(respuesta.data.clave)
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setCargando(false)
    }
  }
  return (
    <div className="servicio-clave">
      {clave === null ? (
        <button type="button" className="boton-cabecera" disabled={cargando} onClick={pedir}>
          <Icono nombre="key" tam={18} /> {cargando ? 'Consultando…' : 'Ver la clave'}
        </button>
      ) : (
        <>
          <code>{clave}</code>
          <button type="button" onClick={() => setClave(null)}>
            Ocultar
          </button>
        </>
      )}
      {error && (
        <span role="alert" className="campo-error">
          {error}
        </span>
      )}
    </div>
  )
}

/** Ficha de una orden de servicio: datos del cliente y del equipo, accesorios, revisiones e historial. */
export default function OrdenFichaPage() {
  const { id } = useParams()
  const ubicacion = useLocation()
  const [asignando, setAsignando] = useState(false)
  const consulta = useQuery({
    queryKey: ['servicio', 'orden', id],
    queryFn: ({ signal }) => api.get(`/servicio-tecnico/ordenes/${id}/`, { signal }).then((r) => r.data),
  })
  const o = consulta.data
  const { imprimir, portal } = useImpresionDocumento(o ? especificacionIngreso(o) : null)
  // Recién registrada: la hoja de ingreso se abre sola, una vez, lista para imprimir.
  const abierta = useRef(false)
  useEffect(() => {
    if (o && ubicacion.state?.imprimir && !abierta.current) {
      abierta.current = true
      imprimir()
    }
  }, [o, ubicacion.state, imprimir])
  const estado = o && ESTADOS_ORDEN[o.estado]

  return (
    <main className="listado compra-pagina">
      <BotonVolver ruta={RUTA} texto="Volver a las órdenes" />
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(o)}>
        {o && (
          <>
            <CabeceraListado icono="wrench" titulo={`Orden ${o.codigo}`} descripcion={`${o.equipo_descripcion} · ${o.cliente_nombre}`}>
              <span className="pildora" data-tono={estado?.tono ?? 'gris'}>
                {estado?.texto ?? o.estado_nombre}
              </span>
              {o.es_garantia && (
                <span className="pildora" data-tono="cian">
                  Garantía
                </span>
              )}
              {o.prioridad === 'URGENTE' && (
                <span className="pildora" data-tono="rojo">
                  Urgente
                </span>
              )}
              <button type="button" className="primario boton-cabecera" onClick={imprimir}>
                <Icono nombre="documento" tam={18} /> Imprimir
              </button>
            </CabeceraListado>

            <PanelEstado orden={o} />

            <PanelTarjeta icono="user" titulo="Cliente y equipo">
              <dl className="servicio-cabecera-ficha">
                <Dato titulo="Cliente">
                  {o.cliente_nombre}
                  <span className="sub-texto">{o.cliente_documento}</span>
                </Dato>
                <Dato titulo="Teléfono">{o.cliente_telefono || '—'}</Dato>
                <Dato titulo="Equipo">
                  {o.equipo_descripcion}
                  {o.equipo_datos.color && <span className="sub-texto">Color {o.equipo_datos.color}</span>}
                </Dato>
                <Dato titulo="Ingresos de este equipo">{o.n_ingresos_equipo === 1 ? 'Primer ingreso' : `${o.n_ingresos_equipo} ingresos`}</Dato>
                <Dato titulo="Ingresó">
                  {fechaHora(o.fecha_ingreso)}
                  <span className="sub-texto">Recibido por {o.recibido_por || '—'}</span>
                </Dato>
                <Dato titulo="Fecha prometida">
                  <span className={o.atrasada ? 'servicio-atrasada' : undefined}>{o.fecha_promesa ? fechaCorta(o.fecha_promesa) : '—'}</span>
                  {o.atrasada && <span className="sub-texto servicio-atrasada">Atrasada</span>}
                </Dato>
                <Dato titulo="Técnico">
                  {o.tecnico_nombre || 'Sin asignar'}
                  {o.permite.asignar && (
                    <button type="button" className="boton-cabecera" onClick={() => setAsignando(true)}>
                      {o.tecnico ? 'Cambiar' : 'Asignar'}
                    </button>
                  )}
                </Dato>
                <Dato titulo="Tipo de servicio">{o.tipo_servicio_nombre || 'Aún no se define'}</Dato>
                {o.sucursal_nombre && <Dato titulo="Tienda">{o.sucursal_nombre}</Dato>}
                {o.equipo_datos.descripcion && <Dato titulo="Características">{o.equipo_datos.descripcion}</Dato>}
              </dl>
            </PanelTarjeta>

            <PanelTarjeta icono="documento" titulo="Falla y estado al recibirlo">
              <dl className="servicio-cabecera-ficha">
                <Dato titulo="Falla que reporta el cliente">{o.falla_reportada}</Dato>
                <Dato titulo="Estado físico">{o.estado_fisico || 'Sin observaciones'}</Dato>
                <Dato titulo="Clave o patrón">
                  {o.tiene_clave ? (
                    <Can permiso="SERVICIOS.EJECUTAR" fallback="Registrada (solo la ve quien trabaja el equipo)">
                      <ClaveEquipo id={o.id} />
                    </Can>
                  ) : (
                    'No entregó'
                  )}
                </Dato>
              </dl>
            </PanelTarjeta>

            <DiagnosticoOrden orden={o} />

            <PresupuestoOrden orden={o} />

            <AdelantosOrden orden={o} />

            <PanelTarjeta icono="package" titulo="Accesorios que dejó">
              {o.accesorios.length === 0 ? (
                <p className="estado-vacio">Dejó solo el equipo.</p>
              ) : (
                <ul className="voucher-lista">
                  {o.accesorios.map((a) => (
                    <li key={a.id}>
                      <span>{a.cantidad} ×</span>
                      <span>{a.nombre}</span>
                      <span className="celda-suave">{a.detalle}</span>
                    </li>
                  ))}
                </ul>
              )}
            </PanelTarjeta>

            {o.revisiones.length > 0 && (
              <PanelTarjeta icono="scan" titulo="Revisión al recibirlo">
                <div className="marco-tabla">
                  <table className="tabla-datos">
                    <thead>
                      <tr>
                        <th>Revisión</th>
                        <th>Resultado</th>
                        <th>Observación</th>
                      </tr>
                    </thead>
                    <tbody>
                      {o.revisiones.map((r) => (
                        <tr key={r.id}>
                          <td>{r.nombre}</td>
                          <td>
                            <span className="pildora" data-tono={r.resultado === 'FALLA' ? 'rojo' : r.resultado === 'OK' ? 'verde' : 'gris'}>
                              {r.resultado_nombre}
                            </span>
                          </td>
                          <td className="celda-suave">{r.observacion || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </PanelTarjeta>
            )}

            <AvisosOrden orden={o} />

            <EntregaGarantiaOrden orden={o} />

            <PanelTarjeta icono="reloj" titulo="Historial" descripcion="Cada cambio de estado, quién lo hizo y cuándo.">
              <ol className="servicio-historial">
                {[...o.historial].reverse().map((h) => (
                  <li key={h.id}>
                    <strong>{h.estado_nuevo_nombre}</strong>
                    <span className="sub-texto">
                      {fechaHora(h.fecha)} · {h.usuario_nombre || 'Sistema'}
                    </span>
                    {h.motivo && <span>{h.motivo}</span>}
                  </li>
                ))}
              </ol>
            </PanelTarjeta>
          </>
        )}
      </EstadoConsulta>
      {portal}
      {asignando && o && <AsignarTecnicoModal orden={o} onCerrar={() => setAsignando(false)} />}
    </main>
  )
}
