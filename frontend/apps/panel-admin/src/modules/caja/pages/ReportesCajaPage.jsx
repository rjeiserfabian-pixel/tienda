import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../../core/api/client'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { ATAJOS_FECHA, ATAJOS_RANGO } from '../../almacen/reportes'
import { fechaCorta, hoyIso } from '../../almacen/inventario'
import { aniosDisponibles, dinero, MESES, mesActual, nombreDePeriodo, origen, revisarRango } from '../caja'
import { BotonDescarga, Descargas, Rango, Tarjetas } from '../components/ReporteComun'
import '../../almacen/inventario.css'
import '../../compras/compras.css'
import '../caja.css'

const REPORTES = [
  ['libro', 'Libro Caja y Bancos'],
  ['saldos', 'Saldos a una fecha'],
  ['flujo', 'Flujo de caja'],
  ['conceptos', 'Por concepto'],
  ['medios', 'Por método de pago'],
  ['bancarizacion', 'Sin bancarizar'],
]

/** Reportes de caja y bancos: se ven en pantalla y se descargan para el contador. */
export default function ReportesCajaPage() {
  const [reporte, setReporte] = useState('libro')
  return (
    <main className="listado">
      <CabeceraListado icono="chart" titulo="Reportes de caja" descripcion="El dinero de la empresa visto de varias formas. Solo cuentan los movimientos vigentes; los anulados no aparecen. Soles y dólares nunca se suman." />
      <div className="segmentos" role="tablist" aria-label="Reporte">
        {REPORTES.map(([valor, texto]) => (
          <button key={valor} type="button" role="tab" aria-selected={reporte === valor} className={reporte === valor ? 'activo' : undefined} onClick={() => setReporte(valor)}>
            {texto}
          </button>
        ))}
      </div>
      {reporte === 'libro' && <Libro />}
      {reporte === 'saldos' && <Saldos />}
      {reporte === 'flujo' && <Flujo />}
      {reporte === 'conceptos' && <Conceptos />}
      {reporte === 'medios' && <Medios />}
      {reporte === 'bancarizacion' && <SinBancarizar />}
    </main>
  )
}

// ---------------------------------------------------------------------------
function Libro() {
  const { empresaActivaId } = useEmpresas()
  const [periodo, setPeriodo] = useState(() => mesActual())
  const [error, setError] = useState('')
  const params = { empresa: empresaActivaId, ...periodo }
  const consulta = useQuery({
    queryKey: ['caja', 'reporte-libro', params],
    queryFn: ({ signal }) => api.get('/caja/reportes/libro/', { params, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId),
    staleTime: 30_000,
  })
  const datos = consulta.data
  return (
    <section className="reporte-caja" aria-label="Libro Caja y Bancos">
      <div className="panel-reportes">
        <div className="fila-campos">
          <Campo etiqueta="Mes" tipo="select">
            {(p) => (
              <select {...p} value={periodo.mes} onChange={(e) => setPeriodo((v) => ({ ...v, mes: Number(e.target.value) }))}>
                {MESES.map((m, i) => (
                  <option key={m} value={i + 1}>
                    {m}
                  </option>
                ))}
              </select>
            )}
          </Campo>
          <Campo etiqueta="Año" tipo="select">
            {(p) => (
              <select {...p} value={periodo.anio} onChange={(e) => setPeriodo((v) => ({ ...v, anio: Number(e.target.value) }))}>
                {aniosDisponibles().map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            )}
          </Campo>
        </div>
        <Descargas error={error}>
          <BotonDescarga url="/caja/reportes/libro/excel/" params={params} texto="Excel" primario onError={setError} />
          <BotonDescarga url="/caja/reportes/libro/ple/" params={{ ...params, formato: '1.1' }} texto="TXT 1.1 (efectivo)" onError={setError} />
          <BotonDescarga url="/caja/reportes/libro/ple/" params={{ ...params, formato: '1.2' }} texto="TXT 1.2 (bancos)" onError={setError} />
        </Descargas>
        <p className="compra-aviso">
          Los archivos TXT para el PLE de SUNAT son un <strong>borrador</strong>: antes de declarar, tu contador debe revisarlos en el programa PLE. Cada caja y cuenta necesita su cuenta contable (y los bancos, su código SUNAT) en «Cajas y cuentas». Las cuentas en dólares no se incluyen.
        </p>
      </div>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(datos)}>
        {datos && (
          <>
            <Formato titulo="Formato 1.1 · Movimiento del efectivo" secciones={datos.efectivo} />
            <Formato titulo="Formato 1.2 · Movimiento de las cuentas de banco" secciones={datos.bancos} />
          </>
        )}
      </EstadoConsulta>
    </section>
  )
}

function Formato({ titulo, secciones }) {
  return (
    <section className="caja-grupo" aria-label={titulo}>
      <h3>{titulo}</h3>
      {secciones.length === 0 && <p className="estado-vacio">No hay cuentas de este tipo.</p>}
      {secciones.map((s) => (
        <div key={s.cuenta} className="libro-cuenta">
          <h4>
            {s.nombre} <small className="celda-suave">({s.moneda === 'USD' ? 'US$' : 'S/'}{s.banco ? ` · ${s.banco}` : ''})</small>
          </h4>
          <div className="marco-tabla">
            <table className="tabla-datos">
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>N°</th>
                  <th>Concepto</th>
                  <th>Origen</th>
                  <th className="num">Debe</th>
                  <th className="num">Haber</th>
                  <th className="num">Saldo</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td colSpan={6} className="celda-suave">
                    Saldo inicial
                  </td>
                  <td className="num">{dinero(s.saldo_inicial, s.moneda)}</td>
                </tr>
                {s.lineas.map((l) => {
                  const o = origen(l.origen)
                  return (
                    <tr key={`${l.numero ?? 'apertura'}-${l.fecha}`}>
                      <td>{fechaCorta(l.fecha)}</td>
                      <td className="celda-suave">{l.numero === null ? '' : String(l.numero).padStart(6, '0')}</td>
                      <td className="col-texto">
                        {l.concepto}
                        {(l.glosa || l.referencia) && (
                          <span className="sub-texto">
                            {l.glosa}
                            {l.referencia ? ` · Operación ${l.referencia}` : ''}
                          </span>
                        )}
                      </td>
                      <td>{l.origen === 'APERTURA' ? '' : <span className="pildora" data-tono={o.tono}>{o.texto}</span>}</td>
                      <td className="num caja-ingreso">{Number(l.debe) ? dinero(l.debe, s.moneda) : ''}</td>
                      <td className="num caja-egreso">{Number(l.haber) ? dinero(l.haber, s.moneda) : ''}</td>
                      <td className="num">{dinero(l.saldo, s.moneda)}</td>
                    </tr>
                  )
                })}
                <tr>
                  <th colSpan={4}>Totales del mes</th>
                  <th className="num">{dinero(s.total_debe, s.moneda)}</th>
                  <th className="num">{dinero(s.total_haber, s.moneda)}</th>
                  <th className="num">{dinero(s.saldo_final, s.moneda)}</th>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </section>
  )
}

// ---------------------------------------------------------------------------
function Saldos() {
  const { empresaActivaId } = useEmpresas()
  const [fecha, setFecha] = useState(hoyIso())
  const [error, setError] = useState('')
  const params = { empresa: empresaActivaId, fecha }
  const consulta = useQuery({
    queryKey: ['caja', 'reporte-saldos', params],
    queryFn: ({ signal }) => api.get('/caja/reportes/saldos/', { params, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId) && Boolean(fecha) && fecha <= hoyIso(),
    staleTime: 30_000,
  })
  const datos = consulta.data
  return (
    <section className="reporte-caja" aria-label="Saldos a una fecha">
      <div className="panel-reportes">
        <div className="fila-campos">
          <Campo etiqueta="Saldos al cierre del" icono="calendario">
            {(p) => <input {...p} type="date" max={hoyIso()} value={fecha} onChange={(e) => setFecha(e.target.value)} />}
          </Campo>
        </div>
        <div className="atajos" aria-label="Atajos de fecha">
          {ATAJOS_FECHA.map((a) => (
            <button key={a.id} type="button" className={`atajo${a.fecha() === fecha ? ' activo' : ''}`} aria-pressed={a.fecha() === fecha} onClick={() => setFecha(a.fecha())}>
              {a.texto}
            </button>
          ))}
        </div>
        <Descargas error={error}>
          <BotonDescarga url="/caja/reportes/saldos/excel/" params={params} texto="Excel" primario deshabilitado={!fecha || fecha > hoyIso()} onError={setError} />
        </Descargas>
      </div>
      {fecha > hoyIso() && <p className="estado-vacio">La fecha no puede ser futura.</p>}
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(datos)}>
        {datos && (
          <>
            <Tarjetas titulo="Total por moneda" filas={datos.totales} etiqueta={(t) => `Total en ${t.moneda === 'USD' ? 'dólares' : 'soles'}`} />
            <div className="marco-tabla">
              <table className="tabla-datos">
                <thead>
                  <tr>
                    <th>Caja o cuenta</th>
                    <th>Tipo</th>
                    <th>Tienda</th>
                    <th className="num">Saldo</th>
                  </tr>
                </thead>
                <tbody>
                  {datos.cuentas.map((c) => (
                    <tr key={c.cuenta}>
                      <td>{c.nombre}</td>
                      <td className="celda-suave">{c.tipo_nombre}</td>
                      <td className="celda-suave">{c.sucursal || '—'}</td>
                      <td className={`num ${Number(c.saldo) < 0 ? 'caja-egreso' : ''}`}>{dinero(c.saldo, c.moneda)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </EstadoConsulta>
    </section>
  )
}

// ---------------------------------------------------------------------------
function Flujo() {
  const { empresaActivaId } = useEmpresas()
  const [rango, setRango] = useState(() => ATAJOS_RANGO[2].rango())
  const [agrupar, setAgrupar] = useState('mes')
  const [meses, setMeses] = useState(3)
  const [error, setError] = useState('')
  const pendiente = revisarRango(rango, hoyIso())
  const params = { empresa: empresaActivaId, ...rango, agrupar }
  const consulta = useQuery({
    queryKey: ['caja', 'reporte-flujo', params],
    queryFn: ({ signal }) => api.get('/caja/reportes/flujo/', { params, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId) && !pendiente,
    staleTime: 30_000,
    retry: false,
  })
  const proyeccion = useQuery({
    queryKey: ['caja', 'reporte-proyeccion', empresaActivaId, meses],
    queryFn: ({ signal }) => api.get('/caja/reportes/proyeccion/', { params: { empresa: empresaActivaId, meses }, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId),
    staleTime: 30_000,
  })
  const datos = consulta.data
  return (
    <section className="reporte-caja" aria-label="Flujo de caja">
      <div className="panel-reportes">
        <Rango rango={rango} setRango={setRango} />
        <div className="segmentos" role="radiogroup" aria-label="Agrupar por">
          {[['mes', 'Por mes'], ['dia', 'Por día']].map(([valor, texto]) => (
            <button key={valor} type="button" role="radio" aria-checked={agrupar === valor} className={agrupar === valor ? 'activo' : undefined} onClick={() => setAgrupar(valor)}>
              {texto}
            </button>
          ))}
        </div>
        <Descargas error={error}>
          <BotonDescarga url="/caja/reportes/flujo/excel/" params={params} texto="Excel" primario deshabilitado={Boolean(pendiente)} onError={setError} />
        </Descargas>
        <p className="celda-suave">{pendiente || 'No incluye lo que solo pasa de una cuenta propia a otra (transferencias, depósitos y retiros).'}</p>
      </div>
      {!pendiente && (
        <EstadoConsulta consulta={consulta} hayDatos={Boolean(datos)}>
          {datos && (
            <>
              <Tarjetas titulo="Neto del periodo" filas={datos.totales} clave="neto" etiqueta={(t) => `Neto en ${t.moneda === 'USD' ? 'dólares' : 'soles'}`} />
              <p className="celda-suave">
                Saldo al inicio: {datos.saldo_inicial.map((s) => dinero(s.saldo, s.moneda)).join(' · ') || '—'} · al final: {datos.saldo_final.map((s) => dinero(s.saldo, s.moneda)).join(' · ') || '—'}
              </p>
              <div className="marco-tabla">
                <table className="tabla-datos">
                  <thead>
                    <tr>
                      <th>Periodo</th>
                      <th>Moneda</th>
                      <th className="num">Ingresos</th>
                      <th className="num">Egresos</th>
                      <th className="num">Neto</th>
                    </tr>
                  </thead>
                  <tbody>
                    {datos.filas.length === 0 && (
                      <tr>
                        <td colSpan={5} className="estado-vacio">
                          No hubo movimientos en ese periodo.
                        </td>
                      </tr>
                    )}
                    {datos.filas.map((f) => (
                      <tr key={`${f.periodo}-${f.moneda}`}>
                        <td>{nombreDePeriodo(f.periodo)}</td>
                        <td className="celda-suave">{f.moneda === 'USD' ? 'Dólares' : 'Soles'}</td>
                        <td className="num caja-ingreso">{dinero(f.ingresos, f.moneda)}</td>
                        <td className="num caja-egreso">{dinero(f.egresos, f.moneda)}</td>
                        <td className="num">{dinero(f.neto, f.moneda)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </EstadoConsulta>
      )}

      <section className="caja-grupo" aria-label="Lo que viene">
        <h3>Lo que viene: pagos a proveedores y gastos por pagar</h3>
        <div className="segmentos" role="radiogroup" aria-label="Meses por delante">
          {[3, 6, 12].map((n) => (
            <button key={n} type="button" role="radio" aria-checked={meses === n} className={meses === n ? 'activo' : undefined} onClick={() => setMeses(n)}>
              {n} meses
            </button>
          ))}
        </div>
        <EstadoConsulta consulta={proyeccion} hayDatos={Boolean(proyeccion.data)}>
          {proyeccion.data && (
            <>
              <p className="celda-suave">
                Hoy hay {proyeccion.data.saldo_hoy.map((s) => dinero(s.saldo, s.moneda)).join(' · ') || '—'}. Se restan las cuotas de compras a crédito y los gastos por pagar que aún no se pagan. Aún no se suman cobros: llegarán con las ventas a crédito.
              </p>
              <div className="marco-tabla">
                <table className="tabla-datos">
                  <thead>
                    <tr>
                      <th>Vence en</th>
                      <th>Moneda</th>
                      <th className="num">Por pagar</th>
                      <th className="num">Saldo que quedaría</th>
                    </tr>
                  </thead>
                  <tbody>
                    {proyeccion.data.filas.length === 0 && (
                      <tr>
                        <td colSpan={4} className="estado-vacio">
                          No hay cuotas por pagar en ese plazo.
                        </td>
                      </tr>
                    )}
                    {proyeccion.data.filas.map((f) => (
                      <tr key={`${f.periodo}-${f.moneda}`}>
                        <td>{nombreDePeriodo(f.periodo)}</td>
                        <td className="celda-suave">{f.moneda === 'USD' ? 'Dólares' : 'Soles'}</td>
                        <td className="num caja-egreso">
                          {dinero(f.por_pagar, f.moneda)}
                          {Number(f.de_gastos) > 0 && <span className="sub-texto">{dinero(f.de_gastos, f.moneda)} son gastos</span>}
                        </td>
                        <td className={`num ${Number(f.saldo_proyectado) < 0 ? 'caja-egreso' : ''}`}>{dinero(f.saldo_proyectado, f.moneda)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </EstadoConsulta>
      </section>
    </section>
  )
}

// ---------------------------------------------------------------------------
function Conceptos() {
  const { empresaActivaId } = useEmpresas()
  const [rango, setRango] = useState(() => ATAJOS_RANGO[0].rango())
  const [error, setError] = useState('')
  const pendiente = revisarRango(rango, hoyIso())
  const params = { empresa: empresaActivaId, ...rango }
  const consulta = useQuery({
    queryKey: ['caja', 'reporte-conceptos', params],
    queryFn: ({ signal }) => api.get('/caja/reportes/conceptos/', { params, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId) && !pendiente,
    staleTime: 30_000,
    retry: false,
  })
  const datos = consulta.data
  return (
    <section className="reporte-caja" aria-label="Movimientos por concepto">
      <div className="panel-reportes">
        <Rango rango={rango} setRango={setRango} />
        <Descargas error={error}>
          <BotonDescarga url="/caja/reportes/conceptos/excel/" params={params} texto="Excel" primario deshabilitado={Boolean(pendiente)} onError={setError} />
        </Descargas>
        {pendiente && <p className="celda-suave">{pendiente}</p>}
      </div>
      {!pendiente && (
        <EstadoConsulta consulta={consulta} hayDatos={Boolean(datos)}>
          {datos && (
            <>
              <Tarjetas titulo="Totales" filas={datos.totales} clave="total" etiqueta={(t) => `${t.tipo === 'INGRESO' ? 'Ingresos' : 'Egresos'} en ${t.moneda === 'USD' ? 'dólares' : 'soles'}`} />
              <div className="marco-tabla">
                <table className="tabla-datos">
                  <thead>
                    <tr>
                      <th>Concepto</th>
                      <th>Tipo</th>
                      <th>Moneda</th>
                      <th className="num">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {datos.filas.length === 0 && (
                      <tr>
                        <td colSpan={4} className="estado-vacio">
                          No hubo movimientos en ese periodo.
                        </td>
                      </tr>
                    )}
                    {datos.filas.map((f) => (
                      <tr key={`${f.concepto}-${f.tipo}-${f.moneda}`}>
                        <td>{f.concepto}</td>
                        <td>
                          <span className="pildora" data-tono={f.tipo === 'INGRESO' ? 'verde' : 'rojo'}>
                            {f.tipo === 'INGRESO' ? 'Ingreso' : 'Egreso'}
                          </span>
                        </td>
                        <td className="celda-suave">{f.moneda === 'USD' ? 'Dólares' : 'Soles'}</td>
                        <td className={`num ${f.tipo === 'INGRESO' ? 'caja-ingreso' : 'caja-egreso'}`}>{dinero(f.total, f.moneda)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </EstadoConsulta>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
function SinBancarizar() {
  const { empresaActivaId } = useEmpresas()
  const [rango, setRango] = useState(() => ATAJOS_RANGO[0].rango())
  const pendiente = revisarRango(rango, hoyIso())
  const params = { empresa: empresaActivaId, ...rango }
  const consulta = useQuery({
    queryKey: ['caja', 'reporte-bancarizacion', params],
    queryFn: ({ signal }) => api.get('/caja/reportes/bancarizacion/', { params, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId) && !pendiente,
    staleTime: 30_000,
    retry: false,
  })
  const datos = consulta.data
  return (
    <section className="reporte-caja" aria-label="Operaciones grandes en efectivo">
      <div className="panel-reportes">
        <Rango rango={rango} setRango={setRango} />
        <p className="compra-aviso">
          La ley de bancarización pide usar un medio de pago del sistema financiero (transferencia, depósito, tarjeta) desde S/ 2 000 o US$ 500. Aquí salen los pagos y cobros en efectivo que llegan a ese límite, para que tu contador los revise. Los límites están por confirmar con él.
        </p>
        {pendiente && <p className="celda-suave">{pendiente}</p>}
      </div>
      {!pendiente && (
        <EstadoConsulta consulta={consulta} hayDatos={Boolean(datos)}>
          {datos && (
            <>
              <p className="celda-suave">{datos.total === 0 ? 'No hay operaciones grandes en efectivo en este periodo.' : `${datos.total} operaciones${datos.truncado ? ' (se muestran las primeras)' : ''}.`}</p>
              {datos.filas.length > 0 && (
                <div className="marco-tabla">
                  <table className="tabla-datos">
                    <thead>
                      <tr>
                        <th>Fecha</th>
                        <th>N°</th>
                        <th>Caja</th>
                        <th>Concepto</th>
                        <th className="num">Ingreso</th>
                        <th className="num">Egreso</th>
                      </tr>
                    </thead>
                    <tbody>
                      {datos.filas.map((m) => (
                        <tr key={m.id}>
                          <td>{fechaCorta(m.fecha)}</td>
                          <td className="celda-suave">{String(m.numero).padStart(6, '0')}</td>
                          <td>{m.cuenta_nombre}</td>
                          <td className="col-texto">
                            {m.concepto_nombre}
                            {(m.glosa || m.referencia) && (
                              <span className="sub-texto">
                                {m.glosa}
                                {m.referencia ? ` · Operación ${m.referencia}` : ''}
                              </span>
                            )}
                          </td>
                          <td className="num caja-ingreso">{m.tipo === 'INGRESO' ? dinero(m.monto, m.moneda) : ''}</td>
                          <td className="num caja-egreso">{m.tipo === 'EGRESO' ? dinero(m.monto, m.moneda) : ''}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </EstadoConsulta>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
function Medios() {
  const { empresaActivaId } = useEmpresas()
  const [rango, setRango] = useState(() => ATAJOS_RANGO[0].rango())
  const [error, setError] = useState('')
  const pendiente = revisarRango(rango, hoyIso())
  const params = { empresa: empresaActivaId, ...rango }
  const consulta = useQuery({
    queryKey: ['caja', 'reporte-medios', params],
    queryFn: ({ signal }) => api.get('/caja/reportes/medios/', { params, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId) && !pendiente,
    staleTime: 30_000,
    retry: false,
  })
  const datos = consulta.data
  return (
    <section className="reporte-caja" aria-label="Movimientos por método de pago">
      <div className="panel-reportes">
        <Rango rango={rango} setRango={setRango} />
        <Descargas error={error}>
          <BotonDescarga url="/caja/reportes/medios/excel/" params={params} texto="Excel" primario deshabilitado={Boolean(pendiente)} onError={setError} />
        </Descargas>
        <p className="celda-suave">{pendiente || 'Compara cuánto entró y salió en efectivo, por transferencia, por Yape… No incluye lo que solo pasa de una cuenta propia a otra.'}</p>
      </div>
      {!pendiente && (
        <EstadoConsulta consulta={consulta} hayDatos={Boolean(datos)}>
          {datos && (
            <div className="marco-tabla">
              <table className="tabla-datos">
                <thead>
                  <tr>
                    <th>Método</th>
                    <th>Moneda</th>
                    <th className="num">Movimientos</th>
                    <th className="num">Entró</th>
                    <th className="num">Salió</th>
                    <th className="num">Neto</th>
                  </tr>
                </thead>
                <tbody>
                  {datos.filas.length === 0 && (
                    <tr>
                      <td colSpan={6} className="estado-vacio">
                        No hubo movimientos en ese periodo.
                      </td>
                    </tr>
                  )}
                  {datos.filas.map((f) => (
                    <tr key={`${f.medio}-${f.moneda}`}>
                      <td>{f.medio}</td>
                      <td className="celda-suave">{f.moneda === 'USD' ? 'Dólares' : 'Soles'}</td>
                      <td className="num">{f.cantidad}</td>
                      <td className="num caja-ingreso">{Number(f.ingresos) ? dinero(f.ingresos, f.moneda) : ''}</td>
                      <td className="num caja-egreso">{Number(f.egresos) ? dinero(f.egresos, f.moneda) : ''}</td>
                      <td className="num">{dinero(f.neto, f.moneda)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </EstadoConsulta>
      )}
    </section>
  )
}
