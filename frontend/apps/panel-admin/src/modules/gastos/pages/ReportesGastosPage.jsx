import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../../core/api/client'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { fechaCorta, hoyIso } from '../../almacen/inventario'
import { ATAJOS_RANGO } from '../../almacen/reportes'
import { nombreDePeriodo, revisarRango } from '../../caja/caja'
import { BotonDescarga, Descargas, Rango, Tarjetas } from '../../caja/components/ReporteComun'
import { dinero } from '../gastos'
import '../../almacen/inventario.css'
import '../../compras/compras.css'
import '../../caja/caja.css'
import '../gastos.css'

const REPORTES = [
  ['resumen', 'Por categoría y mes'],
  ['proveedores', 'Por proveedor'],
  ['sin-comprobante', 'Sin comprobante'],
]

/** Reportes de gastos: en qué se va el dinero, con quién y qué gastos no tienen comprobante. */
export default function ReportesGastosPage() {
  const [reporte, setReporte] = useState('resumen')
  return (
    <main className="listado">
      <CabeceraListado icono="chart" titulo="Reportes de gastos" descripcion="En qué gasta la empresa. Cuenta lo que a la empresa le toca: un gasto repartido entre empresas aparece con su parte. Los anulados no cuentan; soles y dólares no se suman." />
      <div className="segmentos" role="tablist" aria-label="Reporte">
        {REPORTES.map(([valor, texto]) => (
          <button key={valor} type="button" role="tab" aria-selected={reporte === valor} className={reporte === valor ? 'activo' : undefined} onClick={() => setReporte(valor)}>
            {texto}
          </button>
        ))}
      </div>
      <Reporte key={reporte} clave={reporte} />
    </main>
  )
}

/** Lo común: rango de fechas, descarga y la consulta; `clave` es la parte final de la ruta del servidor. */
function Reporte({ clave }) {
  const { empresaActivaId } = useEmpresas()
  const [rango, setRango] = useState(() => ATAJOS_RANGO[2].rango())
  const [error, setError] = useState('')
  const pendiente = revisarRango(rango, hoyIso())
  const params = { empresa: empresaActivaId, ...rango }
  const consulta = useQuery({
    queryKey: ['gastos', 'reporte', clave, params],
    queryFn: ({ signal }) => api.get(`/gastos/reportes/${clave}/`, { params, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId) && !pendiente,
    staleTime: 30_000,
    retry: false,
  })
  const datos = consulta.data
  return (
    <section className="reporte-caja" aria-label="Reporte de gastos">
      <div className="panel-reportes">
        <Rango rango={rango} setRango={setRango} />
        <Descargas error={error} permiso="GASTOS.EXPORTAR">
          <BotonDescarga url={`/gastos/reportes/${clave}/excel/`} params={params} texto="Excel" primario deshabilitado={Boolean(pendiente)} onError={setError} />
        </Descargas>
        {pendiente && <p className="celda-suave">{pendiente}</p>}
      </div>
      {!pendiente && (
        <EstadoConsulta consulta={consulta} hayDatos={Boolean(datos)}>
          {datos && clave === 'resumen' && <Resumen datos={datos} />}
          {datos && clave === 'proveedores' && <Proveedores datos={datos} />}
          {datos && clave === 'sin-comprobante' && <SinComprobante datos={datos} />}
        </EstadoConsulta>
      )}
    </section>
  )
}

const nombreMoneda = (m) => (m === 'USD' ? 'dólares' : 'soles')

function Resumen({ datos }) {
  const meses = [...new Set(datos.matriz.flatMap((f) => Object.keys(f.meses)))].sort()
  if (datos.por_categoria.length === 0) return <p className="estado-vacio">No hubo gastos en ese periodo.</p>
  return (
    <>
      <Tarjetas titulo="Total gastado" filas={datos.totales} clave="total" etiqueta={(t) => `Gastado en ${nombreMoneda(t.moneda)}`} />
      <dl className="cxp-tarjetas" aria-label="Con y sin comprobante">
        {datos.totales.map((t) => (
          <div key={t.moneda} data-tono={Number(t.sin_comprobante) > 0 ? 'ambar' : undefined}>
            <dt>Sin comprobante en {nombreMoneda(t.moneda)}</dt>
            <dd>{dinero(t.sin_comprobante, t.moneda)}</dd>
            <small>Con comprobante: {dinero(t.con_comprobante, t.moneda)}</small>
          </div>
        ))}
      </dl>
      <div className="marco-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th>Categoría</th>
              <th>Moneda</th>
              {meses.map((p) => (
                <th key={p} className="num">
                  {nombreDePeriodo(p)}
                </th>
              ))}
              <th className="num">Total</th>
              <th className="num">%</th>
            </tr>
          </thead>
          <tbody>
            {datos.por_categoria.map((c) => {
              const fila = datos.matriz.find((f) => f.categoria === c.categoria && f.moneda === c.moneda)
              return (
                <tr key={`${c.categoria}-${c.moneda}`}>
                  <td>{c.categoria}</td>
                  <td className="celda-suave">{nombreMoneda(c.moneda)}</td>
                  {meses.map((p) => (
                    <td key={p} className="num">
                      {fila?.meses[p] ? dinero(fila.meses[p], c.moneda) : ''}
                    </td>
                  ))}
                  <td className="num">
                    <strong>{dinero(c.monto, c.moneda)}</strong>
                  </td>
                  <td className="num celda-suave">{c.porcentaje}%</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

function Proveedores({ datos }) {
  if (datos.filas.length === 0) return <p className="estado-vacio">No hubo gastos en ese periodo.</p>
  return (
    <div className="marco-tabla">
      <table className="tabla-datos">
        <thead>
          <tr>
            <th>Proveedor</th>
            <th>Documento</th>
            <th>Moneda</th>
            <th className="num">Gastos</th>
            <th className="num">Total</th>
          </tr>
        </thead>
        <tbody>
          {datos.filas.map((f) => (
            <tr key={`${f.proveedor}-${f.documento}-${f.moneda}`}>
              <td>{f.proveedor}</td>
              <td className="celda-suave">{f.documento || '—'}</td>
              <td className="celda-suave">{nombreMoneda(f.moneda)}</td>
              <td className="num">{f.cantidad}</td>
              <td className="num">
                <strong>{dinero(f.monto, f.moneda)}</strong>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SinComprobante({ datos }) {
  if (datos.total_filas === 0) return <p className="estado-vacio">No hubo gastos sin comprobante en ese periodo.</p>
  return (
    <>
      <p className="celda-suave">Estos gastos no sirven como crédito fiscal. Si hay montos grandes o repetidos de una misma persona, conviene pedir el comprobante.</p>
      <div className="marco-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th>Quién lo gastó</th>
              <th>Moneda</th>
              <th className="num">Veces</th>
              <th className="num">Total</th>
            </tr>
          </thead>
          <tbody>
            {datos.por_persona.map((p) => (
              <tr key={`${p.persona}-${p.moneda}`}>
                <td>{p.persona}</td>
                <td className="celda-suave">{nombreMoneda(p.moneda)}</td>
                <td className="num">{p.cantidad}</td>
                <td className="num">
                  <strong>{dinero(p.monto, p.moneda)}</strong>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="marco-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th>Fecha</th>
              <th>N°</th>
              <th>Gasto</th>
              <th>Quién</th>
              <th className="num">Monto</th>
            </tr>
          </thead>
          <tbody>
            {datos.filas.map((f) => (
              <tr key={f.id}>
                <td>{fechaCorta(f.fecha)}</td>
                <td className="celda-suave">{String(f.numero).padStart(6, '0')}</td>
                <td className="col-texto">
                  {f.descripcion}
                  <span className="sub-texto">
                    {f.categoria}
                    {f.repartido ? ' · Parte que le toca' : ''}
                  </span>
                </td>
                <td>{f.gastado_por}</td>
                <td className="num">{dinero(f.monto, f.moneda)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {datos.truncado && <p className="celda-suave">Se muestran los últimos {datos.filas.length} de {datos.total_filas}. El Excel trae todos.</p>}
    </>
  )
}
