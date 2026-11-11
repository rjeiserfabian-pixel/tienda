import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../../core/api/client'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { descargarArchivo, mensajeDeErrorDescarga } from '../../../shared/utils/descarga'
import { cantidad as formatoCantidad, fechaCorta, hoyIso } from '../../almacen/inventario'
import { ATAJOS_RANGO } from '../../almacen/reportes'
import { dinero, MONEDAS } from '../compras'
import '../../almacen/inventario.css'
import '../compras.css'

const VISTAS = {
  PENDIENTES: 'Pendientes de recibir',
  CUMPLIMIENTO: 'Cumplimiento por proveedor',
  DIFERENCIAS: 'Diferencias de precio',
}

function Pendientes({ datos }) {
  const monedas = Object.keys(datos.valor)
  return (
    <>
      <dl className="cxp-tarjetas" aria-label="Resumen de lo pendiente">
        <div data-tono={datos.atrasadas > 0 ? 'ambar' : undefined}>
          <dt>Órdenes atrasadas</dt>
          <dd>{datos.atrasadas}</dd>
        </div>
        {monedas.map((m) => (
          <div key={m}>
            <dt>Valor pendiente (sin IGV)</dt>
            <dd>{dinero(datos.valor[m], m)}</dd>
            <small>{MONEDAS[m]?.nombre ?? m}</small>
          </div>
        ))}
      </dl>
      <div className="marco-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th>Orden</th>
              <th>Proveedor</th>
              <th>Producto</th>
              <th>Entrega esperada</th>
              <th className="num">Pedido</th>
              <th className="num">Recibido</th>
              <th className="num">Falta</th>
              <th className="num">Valor</th>
            </tr>
          </thead>
          <tbody>
            {datos.filas.length === 0 && <FilaVacia columnas={8} icono="checklist" titulo="No hay mercadería pendiente" descripcion="Todo lo pedido en órdenes emitidas ya llegó." />}
            {datos.filas.map((f) => (
              <tr key={`${f.orden}-${f.producto_codigo}`}>
                <td>
                  <Link to={`/compras/ordenes/${f.orden}`}>{f.codigo}</Link>
                </td>
                <td className="col-texto">{f.proveedor}</td>
                <td className="col-texto">
                  {f.producto}
                  <span className="sub-texto">
                    {f.producto_codigo} · {f.unidad}
                  </span>
                </td>
                <td>
                  {f.entrega ? fechaCorta(f.entrega) : <span className="celda-suave">—</span>}
                  {f.dias_atraso > 0 && (
                    <span className="pildora" data-tono="rojo">
                      {f.dias_atraso} {f.dias_atraso === 1 ? 'día' : 'días'} de atraso
                    </span>
                  )}
                </td>
                <td className="num">{formatoCantidad(f.pedido)}</td>
                <td className="num">{formatoCantidad(f.recibido)}</td>
                <td className="num">
                  <strong>{formatoCantidad(f.pendiente)}</strong>
                </td>
                <td className="num">{dinero(f.valor, f.moneda)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {datos.truncado && <p className="celda-suave">Se muestran las primeras {datos.filas.length} de {datos.total_filas} filas. El Excel trae todas.</p>}
    </>
  )
}

function Cumplimiento({ filas }) {
  return (
    <div className="marco-tabla">
      <table className="tabla-datos">
        <thead>
          <tr>
            <th>Proveedor</th>
            <th className="num">Órdenes</th>
            <th className="num">Sin recibir</th>
            <th className="num">En parte</th>
            <th className="num">Recibidas</th>
            <th className="num">Cerradas</th>
            <th className="num">Pedido</th>
            <th className="num">Recibido</th>
            <th className="num">% recibido</th>
            <th className="num">Días prom.</th>
            <th className="num">A tiempo</th>
          </tr>
        </thead>
        <tbody>
          {filas.length === 0 && <FilaVacia columnas={11} icono="handshake" titulo="No hay órdenes en ese periodo" descripcion="Prueba con otro rango de fechas." />}
          {filas.map((f) => (
            <tr key={`${f.proveedor}-${f.moneda}`}>
              <td className="col-texto">
                {f.proveedor}
                <span className="sub-texto">
                  {f.tipo_documento} {f.documento} · {MONEDAS[f.moneda]?.nombre ?? f.moneda}
                </span>
              </td>
              <td className="num">{f.ordenes}</td>
              <td className="num">{f.sin_recibir}</td>
              <td className="num">{f.parciales}</td>
              <td className="num">{f.recibidas}</td>
              <td className="num">{f.cerradas}</td>
              <td className="num">{dinero(f.pedido, f.moneda)}</td>
              <td className="num">{dinero(f.recibido, f.moneda)}</td>
              <td className="num">
                <strong>{Number(f.cumplimiento)} %</strong>
              </td>
              <td className="num">{f.dias_promedio ?? '—'}</td>
              <td className="num">{f.con_fecha ? `${f.a_tiempo} de ${f.con_fecha}` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Diferencias({ datos }) {
  const monedas = Object.keys(datos.impacto)
  return (
    <>
      <dl className="cxp-tarjetas" aria-label="Efecto de las diferencias de precio">
        <div>
          <dt>Líneas comparadas</dt>
          <dd>{datos.lineas_comparadas}</dd>
          <small>{datos.total_filas} con precio distinto</small>
        </div>
        {monedas.map((m) => (
          <div key={m} data-tono={Number(datos.impacto[m]) > 0 ? 'ambar' : undefined}>
            <dt>Efecto en el costo (sin IGV)</dt>
            <dd>{dinero(datos.impacto[m], m)}</dd>
            <small>{Number(datos.impacto[m]) > 0 ? 'Pagaste de más' : 'Pagaste de menos'} · {MONEDAS[m]?.nombre ?? m}</small>
          </div>
        ))}
      </dl>
      <div className="marco-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Compra</th>
              <th>Orden</th>
              <th>Producto</th>
              <th className="num">Cantidad</th>
              <th className="num">Pactado</th>
              <th className="num">Facturado</th>
              <th className="num">Diferencia</th>
              <th className="num">Efecto</th>
            </tr>
          </thead>
          <tbody>
            {datos.filas.length === 0 && <FilaVacia columnas={9} icono="checklist" titulo="Sin diferencias de precio" descripcion="Lo facturado coincide con lo pactado en las órdenes de ese periodo." />}
            {datos.filas.map((f) => (
              <tr key={`${f.compra}-${f.producto_codigo}-${f.orden}`}>
                <td>{fechaCorta(f.fecha)}</td>
                <td>
                  {f.comprobante}
                  <span className="sub-texto">{f.proveedor}</span>
                </td>
                <td>
                  <Link to={`/compras/ordenes/${f.orden}`}>{f.codigo}</Link>
                </td>
                <td className="col-texto">{f.producto}</td>
                <td className="num">{formatoCantidad(f.cantidad)}</td>
                <td className="num">{dinero(f.precio_pactado, f.moneda)}</td>
                <td className="num">{dinero(f.precio_facturado, f.moneda)}</td>
                <td className="num">
                  {Number(f.diferencia) > 0 ? '+' : ''}
                  {Number(f.diferencia)} {f.porcentaje ? `(${Number(f.porcentaje) > 0 ? '+' : ''}${Number(f.porcentaje)} %)` : ''}
                </td>
                <td className="num">
                  <strong>{dinero(f.impacto, f.moneda)}</strong>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {datos.truncado && <p className="celda-suave">Se muestran las primeras {datos.filas.length} de {datos.total_filas} filas. El Excel trae todas.</p>}
    </>
  )
}

/** Reportes de órdenes de compra: lo que falta recibir, cómo cumple cada proveedor y qué precios cambiaron. */
export default function ReporteOrdenesPage() {
  const { empresaActivaId } = useEmpresas()
  const notificar = useNotificar()
  const [vista, setVista] = useState('PENDIENTES')
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

  const consulta = useQuery({
    queryKey: ['compras', 'ordenes', 'reporte', params],
    queryFn: ({ signal }) => api.get('/compras/reportes/ordenes/vista/', { params, signal }).then((r) => r.data),
    enabled: !pendiente,
    staleTime: 30_000,
    retry: false,
  })
  const datos = consulta.data

  const descargar = async () => {
    if (descargando || pendiente) return
    setErrorDescarga('')
    setDescargando(true)
    try {
      const nombre = await descargarArchivo('/compras/reportes/ordenes/', params)
      notificar('exito', `Se descargó ${nombre}.`)
    } catch (e) {
      setErrorDescarga(await mensajeDeErrorDescarga(e))
    } finally {
      setDescargando(false)
    }
  }

  return (
    <main className="listado">
      <CabeceraListado icono="chart" titulo="Reporte de órdenes de compra" descripcion="Qué mercadería falta recibir, cómo cumple cada proveedor y qué precios cambiaron respecto a lo pactado. Los pendientes son de hoy; los otros dos, del periodo." />
      <div className="panel-reportes">
        <div className="segmentos" role="radiogroup" aria-label="Qué reporte ver">
          {Object.entries(VISTAS).map(([valor, texto]) => (
            <button key={valor} type="button" role="radio" aria-checked={vista === valor} className={vista === valor ? 'activo' : undefined} onClick={() => setVista(valor)}>
              {texto}
            </button>
          ))}
        </div>
        {vista !== 'PENDIENTES' && (
          <>
            <div className="fila-campos">
              <Campo etiqueta={vista === 'CUMPLIMIENTO' ? 'Órdenes desde' : 'Compras desde'} icono="calendario">
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
          </>
        )}
        <div className="acciones-reporte">
          <span className="celda-suave">{pendiente || 'El Excel trae los tres reportes completos, en tres hojas.'}</span>
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
        <EstadoConsulta consulta={consulta} hayDatos={Boolean(datos)}>
          {datos && vista === 'PENDIENTES' && <Pendientes datos={datos.pendientes} />}
          {datos && vista === 'CUMPLIMIENTO' && <Cumplimiento filas={datos.cumplimiento} />}
          {datos && vista === 'DIFERENCIAS' && <Diferencias datos={datos.diferencias} />}
        </EstadoConsulta>
      )}
    </main>
  )
}
