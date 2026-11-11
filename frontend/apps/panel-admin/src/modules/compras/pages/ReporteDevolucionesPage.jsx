import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../../core/api/client'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { descargarArchivo, mensajeDeErrorDescarga } from '../../../shared/utils/descarga'
import { fechaCorta, hoyIso } from '../../almacen/inventario'
import { ATAJOS_RANGO } from '../../almacen/reportes'
import { dinero, MONEDAS } from '../compras'
import '../../almacen/inventario.css'
import '../compras.css'

const TARJETAS = [
  ['total', 'Total devuelto'],
  ['igv', 'IGV'],
  ['aplicado_a_deuda', 'Rebajó la deuda'],
  ['reembolsado', 'Dinero devuelto'],
  ['saldo_a_favor', 'Saldo a favor'],
]

/** Devoluciones a proveedores en un rango de fechas: resumen por proveedor y detalle, para ver y descargar en Excel. */
export default function ReporteDevolucionesPage() {
  const { empresaActivaId } = useEmpresas()
  const notificar = useNotificar()
  const [rango, setRango] = useState(() => ATAJOS_RANGO[0].rango())
  const [descargando, setDescargando] = useState(false)
  const [errorDescarga, setErrorDescarga] = useState('')

  const pendiente = (() => {
    if (!empresaActivaId) return 'Elija una empresa.'
    if (!rango.desde || !rango.hasta) return 'Indique desde y hasta.'
    if (rango.desde > rango.hasta) return '«Desde» no puede ser posterior a «Hasta».'
    if (rango.hasta > hoyIso()) return '«Hasta» no puede ser una fecha futura.'
    return ''
  })()
  const params = { empresa: empresaActivaId, ...rango }

  const vista = useQuery({
    queryKey: ['compras', 'devoluciones-reporte', params],
    queryFn: ({ signal }) => api.get('/compras/reportes/devoluciones/vista/', { params, signal }).then((r) => r.data),
    enabled: !pendiente,
    staleTime: 30_000,
    retry: false,
  })
  const datos = vista.data
  const monedas = datos ? Object.keys(datos.totales) : []

  const descargar = async () => {
    if (descargando || pendiente) return
    setErrorDescarga('')
    setDescargando(true)
    try {
      const nombre = await descargarArchivo('/compras/reportes/devoluciones/', params)
      notificar('exito', `Se descargó ${nombre}.`)
    } catch (e) {
      setErrorDescarga(await mensajeDeErrorDescarga(e))
    } finally {
      setDescargando(false)
    }
  }

  return (
    <main className="listado">
      <CabeceraListado icono="chart" titulo="Reporte de devoluciones" descripcion="Lo que devolviste a tus proveedores en el periodo, por proveedor: cuánto fue, cuánto rebajó de la deuda, cuánto te devolvieron y cuánto quedó a tu favor. Las devoluciones anuladas no aparecen." />
      <div className="panel-reportes">
        <div className="fila-campos">
          <Campo etiqueta="Desde" icono="calendario">
            {(p) => <input {...p} type="date" max={hoyIso()} value={rango.desde} onChange={(e) => setRango((r) => ({ ...r, desde: e.target.value }))} />}
          </Campo>
          <Campo etiqueta="Hasta" icono="calendario">
            {(p) => <input {...p} type="date" max={hoyIso()} value={rango.hasta} onChange={(e) => setRango((r) => ({ ...r, hasta: e.target.value }))} />}
          </Campo>
        </div>
        <div className="atajos" aria-label="Atajos de periodo">
          {ATAJOS_RANGO.map((a) => {
            const activo = a.rango().desde === rango.desde && a.rango().hasta === rango.hasta
            return (
              <button key={a.id} type="button" className={`atajo${activo ? ' activo' : ''}`} aria-pressed={activo} onClick={() => setRango(a.rango())}>
                {a.texto}
              </button>
            )
          })}
        </div>
        <div className="acciones-reporte">
          <span className="celda-suave">{pendiente || 'El archivo trae el resumen y todas las filas del detalle.'}</span>
          <button type="button" className="primario" disabled={descargando || Boolean(pendiente)} onClick={descargar}>
            <Icono nombre="exportar" tam={19} /> {descargando ? 'Generando…' : 'Excel'}
          </button>
        </div>
        {errorDescarga && (
          <p role="alert" className="campo-error">
            {errorDescarga}
          </p>
        )}
      </div>

      {pendiente ? (
        <p className="estado-vacio">{pendiente}</p>
      ) : (
        <EstadoConsulta consulta={vista} hayDatos={Boolean(datos)}>
          {datos && (
            <>
              {monedas.length === 0 && <p className="estado-vacio">No hay devoluciones en ese periodo. Prueba con otro rango de fechas.</p>}
              {monedas.map((moneda) => (
                <dl key={moneda} className="cxp-tarjetas" aria-label={`Totales en ${MONEDAS[moneda]?.nombre ?? moneda}`}>
                  {TARJETAS.map(([clave, texto]) => (
                    <div key={clave}>
                      <dt>{texto}</dt>
                      <dd>{dinero(datos.totales[moneda][clave], moneda)}</dd>
                      <small>{MONEDAS[moneda]?.nombre ?? moneda}</small>
                    </div>
                  ))}
                </dl>
              ))}
              {monedas.length > 0 && <p className="celda-suave">Salió del inventario por estas devoluciones: {dinero(datos.costo_soles)} (al costo de cada compra, en soles).</p>}

              <div className="marco-tabla">
                <table className="tabla-datos">
                  <caption className="sr-only">Resumen por proveedor</caption>
                  <thead>
                    <tr>
                      <th>Proveedor</th>
                      <th className="num">Devoluciones</th>
                      <th className="num">Total</th>
                      <th className="num">IGV</th>
                      <th className="num">Rebajó la deuda</th>
                      <th className="num">Dinero devuelto</th>
                      <th className="num">Saldo a favor</th>
                    </tr>
                  </thead>
                  <tbody>
                    {datos.resumen.length === 0 && <FilaVacia columnas={7} icono="chart" titulo="No hay devoluciones en ese periodo" descripcion="Prueba con otro rango de fechas." />}
                    {datos.resumen.map((f) => (
                      <tr key={`${f.proveedor}-${f.moneda}`}>
                        <td className="col-texto">
                          {f.proveedor}
                          <span className="sub-texto">
                            {f.tipo_documento} {f.documento} · {MONEDAS[f.moneda]?.nombre ?? f.moneda}
                          </span>
                        </td>
                        <td className="num">{f.cantidad}</td>
                        <td className="num">{dinero(f.total, f.moneda)}</td>
                        <td className="num">{dinero(f.igv, f.moneda)}</td>
                        <td className="num">{dinero(f.aplicado_a_deuda, f.moneda)}</td>
                        <td className="num">{dinero(f.reembolsado, f.moneda)}</td>
                        <td className="num">{dinero(f.saldo_a_favor, f.moneda)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {datos.detalle.length > 0 && (
                <div className="marco-tabla">
                  <table className="tabla-datos">
                    <caption className="sr-only">Detalle de las devoluciones</caption>
                    <thead>
                      <tr>
                        <th>Fecha</th>
                        <th>Proveedor</th>
                        <th>Nota de crédito</th>
                        <th>Compra</th>
                        <th>Motivo</th>
                        <th className="num">Total</th>
                        <th className="num">Costo (S/)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {datos.detalle.map((f) => (
                        <tr key={`${f.numero}-${f.fecha}`}>
                          <td>{fechaCorta(f.fecha)}</td>
                          <td className="col-texto">{f.proveedor}</td>
                          <td>
                            {f.serie ? `${f.serie}-` : ''}
                            {f.comprobante}
                          </td>
                          <td className="celda-suave">{f.compra}</td>
                          <td className="col-texto">
                            {f.motivo}
                            <span className="sub-texto">{f.razon}</span>
                          </td>
                          <td className="num">{dinero(f.total, f.moneda)}</td>
                          <td className="num">{dinero(f.costo_soles)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {datos.truncado && <p className="celda-suave">Se muestran las primeras {datos.detalle.length} de {datos.total_filas} filas del detalle. El Excel trae todas.</p>}
            </>
          )}
        </EstadoConsulta>
      )}
    </main>
  )
}
