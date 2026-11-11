import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../../core/api/client'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { fechaCorta, hoyIso } from '../../almacen/inventario'
import { ATAJOS_RANGO } from '../../almacen/reportes'
import { nombreDePeriodo, revisarRango } from '../../caja/caja'
import { BotonDescarga, Descargas, Rango, Tarjetas } from '../../caja/components/ReporteComun'
import { dinero } from '../../compras/compras'
import { Consolidado, VentasInternas } from '../components/ReportesEntreEmpresas'
import '../../almacen/inventario.css'
import '../../compras/compras.css'
import '../../caja/caja.css'
import '../ventas.css'

const REPORTES = [
  ['resumen', 'Resumen por mes'],
  ['vendedores', 'Por vendedor'],
  ['productos', 'Por producto'],
  ['clientes', 'Por cliente'],
  ['metodos', 'Por método de pago'],
  ['registro', 'Registro de ventas'],
  ['ventas-internas', 'Entre empresas'],
  ['consolidado', 'Consolidado'],
]

// Los dos últimos son de las dos empresas: se ofrecen solo a quien trabaja con ventas internas o ve el consolidado.
const permitido = (clave, tiene) => {
  if (clave === 'ventas-internas') return tiene('VENTAS.VENTA_INTERNA') || tiene('VENTAS.LIQUIDAR_INTERNA')
  if (clave === 'consolidado') return tiene('REPORTES.CONSOLIDADO.VER')
  return true
}

const nombreMoneda = (m) => (m === 'USD' ? 'dólares' : 'soles')

/** Reportes de ventas: cuánto se vendió, quién, qué, a quién y cómo se cobró. */
export default function ReportesVentasPage() {
  const [reporte, setReporte] = useState('resumen')
  const { tiene } = usePermisos()
  return (
    <main className="listado">
      <CabeceraListado icono="chart" titulo="Reportes de ventas" descripcion="Lo vendido por la empresa, sin los comprobantes anulados y restando las notas de crédito. Soles y dólares no se suman." />
      <div className="segmentos" role="tablist" aria-label="Reporte">
        {REPORTES.filter(([valor]) => permitido(valor, tiene)).map(([valor, texto]) => (
          <button key={valor} type="button" role="tab" aria-selected={reporte === valor} className={reporte === valor ? 'activo' : undefined} onClick={() => setReporte(valor)}>
            {texto}
          </button>
        ))}
      </div>
      <Reporte key={reporte} clave={reporte} />
    </main>
  )
}

/** Lo común: rango de fechas, descarga y consulta; `clave` es la parte final de la ruta del servidor. */
function Reporte({ clave }) {
  const { empresaActivaId } = useEmpresas()
  const [rango, setRango] = useState(() => ATAJOS_RANGO[2].rango())
  const [error, setError] = useState('')
  const pendiente = revisarRango(rango, hoyIso())
  const params = { empresa: empresaActivaId, ...rango }
  const consulta = useQuery({
    queryKey: ['ventas', 'reporte', clave, params],
    queryFn: ({ signal }) => api.get(`/ventas/reportes/${clave}/`, { params, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId) && !pendiente,
    staleTime: 30_000,
    retry: false,
  })
  const datos = consulta.data
  return (
    <section className="reporte-caja" aria-label="Reporte de ventas">
      <div className="panel-reportes">
        <Rango rango={rango} setRango={setRango} />
        <Descargas error={error} permiso="VENTAS.EXPORTAR">
          <BotonDescarga url={`/ventas/reportes/${clave}/excel/`} params={params} texto="Excel" primario deshabilitado={Boolean(pendiente)} onError={setError} />
        </Descargas>
        {pendiente && <p className="celda-suave">{pendiente}</p>}
      </div>
      {!pendiente && (
        <EstadoConsulta consulta={consulta} hayDatos={Boolean(datos)}>
          {datos && clave === 'resumen' && <Resumen datos={datos} />}
          {datos && clave === 'vendedores' && <Ranking datos={datos} columnas={[['vendedor', 'Vendedor']]} />}
          {datos && clave === 'clientes' && <Ranking datos={datos} columnas={[['cliente', 'Cliente'], ['documento', 'Documento']]} />}
          {datos && clave === 'productos' && <Productos datos={datos} />}
          {datos && clave === 'metodos' && <Metodos datos={datos} />}
          {datos && clave === 'registro' && <Registro datos={datos} />}
          {datos && clave === 'ventas-internas' && <VentasInternas datos={datos} />}
          {datos && clave === 'consolidado' && <Consolidado datos={datos} />}
        </EstadoConsulta>
      )}
    </section>
  )
}

const Vacio = () => <p className="estado-vacio">No hubo ventas en ese periodo.</p>

/** Columnas de dinero comunes; el costo y la utilidad llegan solo si el servidor los permite. */
function ColumnasDinero({ datos }) {
  return (
    <>
      <th className="num">Sin IGV</th>
      <th className="num">IGV</th>
      <th className="num">Total</th>
      <th className="num">Notas de crédito</th>
      <th className="num">Neto</th>
      {datos.con_utilidad && (
        <>
          <th className="num">Costo</th>
          <th className="num">Utilidad (S/)</th>
        </>
      )}
    </>
  )
}

function CeldasDinero({ f, datos }) {
  return (
    <>
      <td className="num">{dinero(f.valor, f.moneda)}</td>
      <td className="num">{dinero(f.igv, f.moneda)}</td>
      <td className="num">{dinero(f.total, f.moneda)}</td>
      <td className="num celda-suave">{Number(f.notas) ? dinero(f.notas, f.moneda) : ''}</td>
      <td className="num">
        <strong>{dinero(f.neto, f.moneda)}</strong>
      </td>
      {datos.con_utilidad && (
        <>
          <td className="num">{dinero(f.costo, 'PEN')}</td>
          <td className="num">{dinero(f.utilidad, 'PEN')}</td>
        </>
      )}
    </>
  )
}

function Resumen({ datos }) {
  if (datos.totales.length === 0) return <Vacio />
  return (
    <>
      <Tarjetas titulo="Ventas netas" filas={datos.totales} clave="neto" etiqueta={(t) => `Vendido en ${nombreMoneda(t.moneda)} (neto)`} />
      <dl className="cxp-tarjetas" aria-label="Contado y crédito">
        {datos.totales.map((t) => (
          <div key={t.moneda}>
            <dt>A crédito en {nombreMoneda(t.moneda)}</dt>
            <dd>{dinero(t.credito, t.moneda)}</dd>
            <small>Al contado: {dinero(t.contado, t.moneda)}</small>
          </div>
        ))}
        {datos.con_utilidad &&
          datos.totales.map((t) => (
            <div key={`u-${t.moneda}`}>
              <dt>Utilidad de las ventas en {nombreMoneda(t.moneda)}</dt>
              <dd>{dinero(t.utilidad, 'PEN')}</dd>
              <small>Costo: {dinero(t.costo, 'PEN')} (en soles)</small>
            </div>
          ))}
      </dl>
      <div className="marco-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th>Mes</th>
              <th>Moneda</th>
              <th className="num">Comprobantes</th>
              <ColumnasDinero datos={datos} />
            </tr>
          </thead>
          <tbody>
            {datos.por_mes.map((f) => (
              <tr key={`${f.periodo}-${f.moneda}`}>
                <td>{nombreDePeriodo(f.periodo)}</td>
                <td className="celda-suave">{nombreMoneda(f.moneda)}</td>
                <td className="num">{f.cantidad}</td>
                <CeldasDinero f={f} datos={datos} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function Ranking({ datos, columnas }) {
  if (datos.filas.length === 0) return <Vacio />
  return (
    <div className="marco-tabla">
      <table className="tabla-datos">
        <thead>
          <tr>
            {columnas.map(([campo, titulo]) => (
              <th key={campo}>{titulo}</th>
            ))}
            <th>Moneda</th>
            <th className="num">Comprobantes</th>
            <ColumnasDinero datos={datos} />
          </tr>
        </thead>
        <tbody>
          {datos.filas.map((f) => (
            <tr key={`${columnas.map(([c]) => f[c]).join('|')}-${f.moneda}`}>
              {columnas.map(([campo]) => (
                <td key={campo} className={campo === 'documento' ? 'celda-suave' : undefined}>
                  {f[campo] || '—'}
                </td>
              ))}
              <td className="celda-suave">{nombreMoneda(f.moneda)}</td>
              <td className="num">{f.cantidad}</td>
              <CeldasDinero f={f} datos={datos} />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Productos({ datos }) {
  if (datos.filas.length === 0) return <Vacio />
  return (
    <div className="marco-tabla">
      <table className="tabla-datos">
        <thead>
          <tr>
            <th>Producto</th>
            <th>Moneda</th>
            <th className="num">Unidades</th>
            <th className="num">Ventas sin IGV</th>
            {datos.con_utilidad && (
              <>
                <th className="num">Costo</th>
                <th className="num">Utilidad (S/)</th>
                <th className="num">Margen</th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {datos.filas.map((f) => (
            <tr key={`${f.producto}-${f.moneda}`}>
              <td>{f.producto}</td>
              <td className="celda-suave">{nombreMoneda(f.moneda)}</td>
              <td className="num">{Number(f.unidades)}</td>
              <td className="num">
                <strong>{dinero(f.valor, f.moneda)}</strong>
              </td>
              {datos.con_utilidad && (
                <>
                  <td className="num">{dinero(f.costo, 'PEN')}</td>
                  <td className="num">{dinero(f.utilidad, 'PEN')}</td>
                  <td className="num celda-suave">{f.margen}%</td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Metodos({ datos }) {
  if (datos.filas.length === 0) return <Vacio />
  return (
    <div className="marco-tabla">
      <table className="tabla-datos">
        <thead>
          <tr>
            <th>Método</th>
            <th>Moneda</th>
            <th className="num">Ventas al contado</th>
            <th className="num">Cuotas cobradas</th>
            <th className="num">Devuelto</th>
            <th className="num">Neto</th>
          </tr>
        </thead>
        <tbody>
          {datos.filas.map((f) => (
            <tr key={`${f.metodo}-${f.moneda}`}>
              <td>{f.metodo}</td>
              <td className="celda-suave">{nombreMoneda(f.moneda)}</td>
              <td className="num">{dinero(f.ventas, f.moneda)}</td>
              <td className="num">{dinero(f.cuotas, f.moneda)}</td>
              <td className="num celda-suave">{Number(f.devuelto) ? dinero(f.devuelto, f.moneda) : ''}</td>
              <td className="num">
                <strong>{dinero(f.neto, f.moneda)}</strong>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Registro({ datos }) {
  if (datos.total_filas === 0) return <Vacio />
  return (
    <>
      <div className="marco-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Comprobante</th>
              <th>Cliente</th>
              <th>Vendedor</th>
              <th>Pago</th>
              <th className="num">Sin IGV</th>
              <th className="num">IGV</th>
              <th className="num">Total</th>
              {datos.con_utilidad && <th className="num">Utilidad (S/)</th>}
            </tr>
          </thead>
          <tbody>
            {datos.filas.map((f) => (
              <tr key={`${f.numero}-${f.tipo}`}>
                <td>{fechaCorta(f.fecha)}</td>
                <td>
                  <strong>{f.numero}</strong>
                  <span className="sub-texto">{f.tipo}</span>
                </td>
                <td>{f.cliente}</td>
                <td className="celda-suave">{f.vendedor}</td>
                <td className="celda-suave">{f.forma_pago === 'CREDITO' ? 'Crédito' : 'Contado'}</td>
                <td className="num">{dinero(f.valor, f.moneda)}</td>
                <td className="num">{dinero(f.igv, f.moneda)}</td>
                <td className="num">
                  <strong>{dinero(f.total, f.moneda)}</strong>
                </td>
                {datos.con_utilidad && <td className="num">{dinero(f.utilidad, 'PEN')}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {datos.truncado && <p className="celda-suave">Se muestran los últimos {datos.filas.length} de {datos.total_filas}. El Excel trae todos.</p>}
    </>
  )
}
