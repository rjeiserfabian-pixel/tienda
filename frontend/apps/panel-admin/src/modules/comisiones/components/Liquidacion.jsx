import { useQuery } from '@tanstack/react-query'
import { Fragment, useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import Can from '../../../shared/components/Can'
import Campo from '../../../shared/components/Campo'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { dinero } from '../../compras/compras'
import '../../compras/compras.css'

const SIN_DATOS = []
const TONO = { PENDIENTE: 'ambar', EN_PLANILLA: 'verde', PAGADA_APARTE: 'verde', SIN_MONTO: 'gris' }
const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'setiembre', 'octubre', 'noviembre', 'diciembre']
const nombreDelMes = (periodo) => {
  const [a, m] = periodo.split('-')
  return `${MESES[Number(m) - 1]} de ${a}`
}
const mesSiguiente = (periodo) => {
  const [a, m] = periodo.split('-').map(Number)
  return m === 12 ? `${a + 1}-01` : `${a}-${String(m + 1).padStart(2, '0')}`
}

/** Los pasos de una línea: llevarla a la planilla o marcarla como pagada aparte. */
function Acciones({ linea, periodo, onHecho }) {
  const [paso, setPaso] = useState(null) // null | 'planilla' | 'aparte'
  const [mes, setMes] = useState(mesSiguiente(periodo))
  const [nota, setNota] = useState('')
  const [error, setError] = useState('')
  const alExito = () => {
    setPaso(null)
    onHecho()
  }
  const aPlanilla = useMutacion({
    mutationFn: () => api.post(`/comisiones/liquidaciones/lineas/${linea.id}/planilla/`, { mes }).then((r) => r.data),
    invalidar: [['comisiones']],
    exito: 'Enviada a la planilla.',
    alExito,
    avisarError: false,
  })
  const aparte = useMutacion({
    mutationFn: () => api.post(`/comisiones/liquidaciones/lineas/${linea.id}/pagada/`, { nota }).then((r) => r.data),
    invalidar: [['comisiones']],
    exito: 'Marcada como pagada.',
    alExito,
    avisarError: false,
  })
  if (linea.estado !== 'PENDIENTE' && !(linea.estado === 'EN_PLANILLA')) return null
  if (linea.estado === 'EN_PLANILLA') return <span className="celda-suave">Planilla {linea.planilla_periodo?.slice(0, 7)}</span>
  return (
    <>
      <span className="acciones-fila">
        {linea.tiene_ficha && (
          <button type="button" onClick={() => setPaso('planilla')}>
            Llevar a planilla
          </button>
        )}
        <button type="button" onClick={() => setPaso('aparte')}>
          Pagada aparte
        </button>
      </span>
      {paso && (
        <Modal titulo={paso === 'planilla' ? 'Llevar a la planilla' : 'Marcar como pagada aparte'} subtitulo={`${linea.nombre} · ${dinero(linea.a_pagar, 'PEN')}`} onCerrar={() => setPaso(null)} ancho={460}>
          {paso === 'planilla' ? (
            <>
              <p className="celda-suave">Entra a la planilla como el ingreso «Comisiones» (afecto a pensiones, EsSalud y renta de 5.ª). La planilla de ese mes debe existir y estar en revisión.</p>
              <Campo etiqueta="Planilla del mes" requerido>{(props) => <input {...props} type="month" value={mes} onChange={(e) => setMes(e.target.value)} />}</Campo>
            </>
          ) : (
            <Campo etiqueta="¿Cómo y cuándo se le pagó?" requerido ayuda="Por ejemplo: Transferencia del 15/12.">
              {(props) => <input {...props} maxLength={200} value={nota} onChange={(e) => setNota(e.target.value)} />}
            </Campo>
          )}
          {error && (
            <p role="alert" className="campo-error">
              {error}
            </p>
          )}
          <div className="acciones">
            <button type="button" onClick={() => setPaso(null)}>
              Cancelar
            </button>
            <button
              type="button"
              className="primario"
              disabled={aPlanilla.isPending || aparte.isPending}
              onClick={() => {
                setError('')
                const accion = paso === 'planilla' ? aPlanilla : aparte
                accion.mutate(undefined, { onError: (e) => setError(mensajeDeError(e)) })
              }}
            >
              Confirmar
            </button>
          </div>
        </Modal>
      )}
    </>
  )
}

/** Lo que ganó cada persona en el mes, con el detalle venta por venta. */
function DetalleLiquidacion({ id, onCerrar }) {
  const consulta = useQuery({
    queryKey: ['comisiones', 'liquidacion', id],
    queryFn: ({ signal }) => api.get(`/comisiones/liquidaciones/${id}/`, { signal }).then((r) => r.data),
  })
  const [abierta, setAbierta] = useState(null)
  const d = consulta.data
  return (
    <Modal titulo={d ? `Comisiones de ${nombreDelMes(d.periodo)}` : 'Liquidación'} subtitulo={d ? `A pagar: ${dinero(d.total_a_pagar, 'PEN')}` : undefined} onCerrar={onCerrar} ancho={1000}>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(d)}>
        {d && (
          <div className="marco-tabla">
            <table className="tabla-datos">
              <thead>
                <tr>
                  <th>Persona</th>
                  <th className="num">Ventas</th>
                  <th className="num">Bonos</th>
                  <th className="num">Servicios</th>
                  <th className="num">Saldo anterior</th>
                  <th className="num">A pagar</th>
                  <th>Estado</th>
                  <th className="centrado">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {d.lineas.length === 0 && (
                  <tr>
                    <td colSpan={8} className="celda-suave">
                      Nadie ganó comisión en este mes.
                    </td>
                  </tr>
                )}
                {d.lineas.map((l) => (
                  <Fragment key={l.id}>
                    <tr>
                      <td className="col-texto">
                        <button type="button" onClick={() => setAbierta(abierta === l.id ? null : l.id)} aria-expanded={abierta === l.id}>
                          {l.nombre}
                        </button>
                        {!l.tiene_ficha && <span className="sub-texto">Sin ficha de personal</span>}
                      </td>
                      <td className="num">{dinero(l.comisiones_ventas, 'PEN')}</td>
                      <td className="num">{dinero(l.bonos, 'PEN')}</td>
                      <td className="num">{dinero(l.comisiones_tecnico, 'PEN')}</td>
                      <td className="num">{Number(l.arrastre_anterior) !== 0 ? dinero(l.arrastre_anterior, 'PEN') : '—'}</td>
                      <td className="num">
                        <strong>{dinero(l.a_pagar, 'PEN')}</strong>
                        {Number(l.arrastre_nuevo) !== 0 && <span className="sub-texto">Queda debiendo {dinero(Math.abs(Number(l.arrastre_nuevo)), 'PEN')}</span>}
                      </td>
                      <td>
                        <span className="pildora" data-tono={TONO[l.estado]}>
                          {l.estado_texto}
                        </span>
                        {l.pagada_nota && <span className="sub-texto">{l.pagada_nota}</span>}
                      </td>
                      <td className="centrado">
                        <Can permiso="COMISIONES.LIQUIDAR">
                          <Acciones linea={l} periodo={d.periodo} onHecho={() => consulta.refetch()} />
                        </Can>
                      </td>
                    </tr>
                    {abierta === l.id && (
                      <tr>
                        <td colSpan={8} className="col-texto">
                          {l.detalle.ventas.length > 0 && (
                            <>
                              <strong>Ventas</strong>
                              <ul>
                                {l.detalle.ventas.map((v) => (
                                  <li key={v.comprobante}>
                                    {v.comprobante} (vendido el {v.fecha_venta}): {dinero(v.monto, 'PEN')}
                                  </li>
                                ))}
                              </ul>
                            </>
                          )}
                          {l.detalle.bonos.length > 0 && (
                            <>
                              <strong>Bonos</strong>
                              <ul>
                                {l.detalle.bonos.map((b) => (
                                  <li key={b.nombre}>
                                    {b.nombre} (vendió {dinero(b.ventas_mes, 'PEN')}): {dinero(b.monto, 'PEN')}
                                  </li>
                                ))}
                              </ul>
                            </>
                          )}
                          {l.detalle.ordenes.length > 0 && (
                            <>
                              <strong>Servicio técnico</strong>
                              <ul>
                                {l.detalle.ordenes.map((o) => (
                                  <li key={o.orden}>
                                    Orden {o.orden}: {o.porcentaje} % de {dinero(o.mano_obra, 'PEN')} de mano de obra = {dinero(o.monto, 'PEN')}
                                  </li>
                                ))}
                              </ul>
                            </>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </EstadoConsulta>
    </Modal>
  )
}

/** El cierre de cada mes: lo ganado por cada persona y lo que se le paga. */
export default function Liquidacion() {
  const [abierta, setAbierta] = useState(null)
  const [cerrando, setCerrando] = useState(false)
  const consulta = useQuery({ queryKey: ['comisiones', 'liquidaciones'], queryFn: ({ signal }) => api.get('/comisiones/liquidaciones/', { signal }).then((r) => r.data) })
  const cerrar = useMutacion({
    mutationFn: (mes) => api.post('/comisiones/liquidaciones/', { mes }).then((r) => r.data),
    invalidar: [['comisiones']],
    exito: 'Mes cerrado.',
    alExito: (liq) => {
      setCerrando(false)
      setAbierta(liq.id)
    },
  })
  const porCerrar = consulta.data?.por_cerrar
  const filas = consulta.data?.results ?? SIN_DATOS
  return (
    <section aria-labelledby="titulo-liquidacion">
      <h2 id="titulo-liquidacion">Cierre mensual</h2>
      <p className="celda-suave">Al cerrar un mes se aplica la escala, se otorgan los bonos y se calcula lo que gana cada persona (vendedores y técnicos). Lo que llegue después —una devolución, un abono anulado— se anota en el mes siguiente.</p>
      <Can permiso="COMISIONES.LIQUIDAR">
        {porCerrar ? (
          <button type="button" className="primario" onClick={() => setCerrando(true)}>
            Cerrar {nombreDelMes(porCerrar)}
          </button>
        ) : (
          <p className="celda-suave">No hay un mes terminado por cerrar.</p>
        )}
      </Can>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Mes</th>
                <th>Cerrado el</th>
                <th className="num">Personas</th>
                <th className="num">Total a pagar</th>
                <th>Por pagar</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && (
                <tr>
                  <td colSpan={6} className="celda-suave">
                    Aún no se cerró ningún mes.
                  </td>
                </tr>
              )}
              {filas.map((f) => (
                <tr key={f.id}>
                  <td>
                    <strong>{nombreDelMes(f.periodo)}</strong>
                  </td>
                  <td className="celda-suave">{f.cerrada_en.slice(0, 10)}</td>
                  <td className="num">{f.personas}</td>
                  <td className="num">
                    <strong>{dinero(f.total_a_pagar, 'PEN')}</strong>
                  </td>
                  <td>{f.por_estado.PENDIENTE ? dinero(f.por_estado.PENDIENTE, 'PEN') : '—'}</td>
                  <td className="centrado">
                    <button type="button" onClick={() => setAbierta(f.id)}>
                      Ver detalle
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </EstadoConsulta>
      {abierta && <DetalleLiquidacion id={abierta} onCerrar={() => setAbierta(null)} />}
      {cerrando && porCerrar && (
        <ConfirmarModal
          titulo={`Cerrar ${nombreDelMes(porCerrar)}`}
          mensaje="Se aplicará la escala y se otorgarán los bonos de ese mes. Un mes cerrado no se puede abrir de nuevo: lo que llegue después se anota en el mes siguiente. ¿Cerrarlo ahora?"
          textoConfirmar="Cerrar el mes"
          enviando={cerrar.isPending}
          onConfirmar={() => cerrar.mutate(porCerrar)}
          onCerrar={() => setCerrando(false)}
        />
      )}
    </section>
  )
}
