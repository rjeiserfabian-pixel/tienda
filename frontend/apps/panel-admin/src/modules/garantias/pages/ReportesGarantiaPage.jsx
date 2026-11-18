import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import Can from '../../../shared/components/Can'
import Campo from '../../../shared/components/Campo'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaCorta, hoyIso } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import { sumarDias } from '../../ventas/ventas'
import '../../almacen/inventario.css'
import '../../compras/compras.css'
import '../garantias.css'

const RESOLUCIONES = { REPARADO: 'Reparados', CAMBIADO: 'Cambiados', NOTA_CREDITO: 'Con nota de crédito', RECHAZADO: 'Rechazados' }
const porcentaje = (t) => (t === null || t === undefined ? '—' : `${t.toString().replace('.', ',')} %`)

/** Avisos por correo de garantías por vencer: se encienden aquí y salen solos cada mañana. */
function Avisos({ empresaId }) {
  const consulta = useQuery({
    queryKey: ['garantias', 'configuracion', empresaId],
    queryFn: ({ signal }) => api.get('/garantias/configuracion/', { params: { empresa: empresaId }, signal }).then((r) => r.data),
    enabled: Boolean(empresaId),
  })
  const [borrador, setBorrador] = useState(null)
  const [error, setError] = useState('')
  const datos = consulta.data
  const actual = borrador ?? (datos ? { avisos_activos: datos.avisos_activos, dias_antes: String(datos.dias_antes) } : null)
  const guardar = useMutacion({
    mutationFn: (cuerpo) => api.patch('/garantias/configuracion/', cuerpo, { params: { empresa: empresaId } }).then((r) => r.data),
    invalidar: [['garantias', 'configuracion']],
    exito: 'Avisos guardados.',
    alExito: () => setBorrador(null),
    avisarError: false,
  })
  if (!actual) return null
  const enviar = (evento) => {
    evento.preventDefault()
    setError('')
    const dias = Number(actual.dias_antes)
    if (!Number.isInteger(dias) || dias < 1 || dias > 90) return setError('Los días de anticipación van de 1 a 90.')
    guardar.mutate({ avisos_activos: actual.avisos_activos, dias_antes: dias }, { onError: (e) => setError(mensajeDeError(e)) })
  }
  return (
    <section className="tarjeta-seccion" aria-labelledby="titulo-avisos">
      <h2 id="titulo-avisos">Avisos al cliente</h2>
      <p className="celda-suave">
        Cuando una garantía esté por vencer, el cliente recibe un correo (uno solo por garantía, con un enlace para darse de baja). No se escribe a quien no tiene correo.
      </p>
      <Can
        permiso="VENTAS.GARANTIA_RESOLVER"
        fallback={<p>{datos.avisos_activos ? `Activados: se avisa ${datos.dias_antes} días antes.` : 'Los avisos están desactivados. Los activa un administrador.'}</p>}
      >
        <form onSubmit={enviar} noValidate>
          <label className="casilla">
            <input type="checkbox" checked={actual.avisos_activos} onChange={(e) => setBorrador({ ...actual, avisos_activos: e.target.checked })} /> Avisar a los clientes cuando su garantía esté por vencer
          </label>
          <Campo etiqueta="Días de anticipación" ayuda="De 1 a 90 días antes de que venza.">
            {(props) => <input {...props} type="number" min="1" max="90" step="1" value={actual.dias_antes} onChange={(e) => setBorrador({ ...actual, dias_antes: e.target.value })} />}
          </Campo>
          {error && (
            <p role="alert" className="campo-error">
              {error}
            </p>
          )}
          <div className="acciones">
            <button type="submit" className="primario" disabled={guardar.isPending || borrador === null}>
              {guardar.isPending ? 'Guardando…' : 'Guardar'}
            </button>
          </div>
        </form>
      </Can>
      <p className="celda-suave">
        Enviados: {datos.avisos.ENVIADO} · Sin enviar (sin correo o con baja): {datos.avisos.OMITIDO} · Con error: {datos.avisos.FALLIDO}
      </p>
    </section>
  )
}

function Tarjeta({ titulo, valor, nota, tono }) {
  return (
    <div data-tono={tono}>
      <dt>{titulo}</dt>
      <dd>{valor}</dd>
      {nota && <small>{nota}</small>}
    </div>
  )
}

/** Reportes de garantías: cómo están, qué marcas y productos fallan más y cuánto cuestan los cambios. */
export default function ReportesGarantiaPage() {
  const { empresaActivaId } = useEmpresas()
  const hoy = hoyIso()
  const [desde, setDesde] = useState(sumarDias(hoy, -90))
  const [hasta, setHasta] = useState(hoy)
  const consulta = useQuery({
    queryKey: ['garantias', 'reportes', empresaActivaId, desde, hasta],
    queryFn: ({ signal }) => api.get('/garantias/reportes/', { params: { empresa: empresaActivaId, desde, hasta }, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId && desde && hasta && desde <= hasta),
  })
  const d = consulta.data

  return (
    <main className="listado">
      <CabeceraListado icono="chart" titulo="Reportes de garantía" descripcion="Cómo están las garantías, qué falla más y qué pasó con los reclamos." />

      <div className="filtros-panel" role="search">
        <label>
          Desde
          <input type="date" value={desde} max={hasta} onChange={(e) => setDesde(e.target.value)} />
        </label>
        <label>
          Hasta
          <input type="date" value={hasta} min={desde} max={hoy} onChange={(e) => setHasta(e.target.value)} />
        </label>
      </div>
      {desde > hasta && <p role="alert" className="campo-error">La fecha «desde» no puede ser posterior a «hasta».</p>}

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(d)}>
        {d && (
          <>
            <dl className="cxp-tarjetas" aria-label="Situación de las garantías hoy">
              <Tarjeta titulo="Vigentes" valor={d.situacion.vigentes} nota="Con más de 30 días" />
              <Tarjeta titulo="Por vencer" valor={d.situacion.por_vencer} nota="En los próximos 30 días" tono={d.situacion.por_vencer > 0 ? 'ambar' : undefined} />
              <Tarjeta titulo="Vencidas" valor={d.situacion.vencidas} />
              <Tarjeta titulo="Reclamos abiertos" valor={d.reclamos.abiertos} nota={`${d.reclamos.total} en el periodo`} tono={d.reclamos.abiertos > 0 ? 'ambar' : undefined} />
              <Tarjeta titulo="Días para resolver" valor={d.reclamos.dias_promedio === null ? '—' : String(d.reclamos.dias_promedio).replace('.', ',')} nota="Promedio de los cerrados" />
              <Tarjeta titulo="Unidades con garantía vendidas" valor={d.vendidas} nota={`${fechaCorta(d.periodo.desde)} al ${fechaCorta(d.periodo.hasta)}`} />
            </dl>

            <h2>Falla por marca</h2>
            <div className="marco-tabla">
              <table className="tabla-datos">
                <thead>
                  <tr>
                    <th>Marca</th>
                    <th className="num">Vendidas</th>
                    <th className="num">Reclamos</th>
                    <th className="num">Unidades reclamadas</th>
                    <th className="num">% de falla</th>
                  </tr>
                </thead>
                <tbody>
                  {d.por_marca.length === 0 && (
                    <tr>
                      <td colSpan={5} className="celda-suave">
                        No hay ventas con garantía ni reclamos en este periodo.
                      </td>
                    </tr>
                  )}
                  {d.por_marca.map((m) => (
                    <tr key={m.marca}>
                      <td>{m.marca}</td>
                      <td className="num">{m.vendidas}</td>
                      <td className="num">{m.reclamos}</td>
                      <td className="num">{m.reclamadas}</td>
                      <td className="num">{porcentaje(m.tasa)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <h2>Productos con más reclamos</h2>
            <div className="marco-tabla">
              <table className="tabla-datos">
                <thead>
                  <tr>
                    <th>Producto</th>
                    <th className="num">Reclamos</th>
                    <th className="num">Unidades reclamadas</th>
                    <th className="num">Vendidas en el periodo</th>
                    <th className="num">% de falla</th>
                  </tr>
                </thead>
                <tbody>
                  {d.por_producto.length === 0 && (
                    <tr>
                      <td colSpan={5} className="celda-suave">
                        No hubo reclamos en este periodo.
                      </td>
                    </tr>
                  )}
                  {d.por_producto.map((p) => (
                    <tr key={p.producto}>
                      <td>{p.producto}</td>
                      <td className="num">{p.reclamos}</td>
                      <td className="num">{p.reclamadas}</td>
                      <td className="num">{p.vendidas}</td>
                      <td className="num">{porcentaje(p.tasa)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="celda-suave">
              El % de falla compara lo reclamado con lo vendido en el mismo periodo; un producto vendido antes y reclamado ahora puede pasar de 100 %.
            </p>

            <h2>Cómo se resolvieron</h2>
            <p>
              {Object.keys(RESOLUCIONES).every((k) => !d.reclamos.por_resolucion[k])
                ? 'Todavía no hay reclamos resueltos en este periodo.'
                : Object.entries(RESOLUCIONES)
                    .filter(([clave]) => d.reclamos.por_resolucion[clave])
                    .map(([clave, texto]) => `${texto}: ${d.reclamos.por_resolucion[clave]}`)
                    .join(' · ')}
            </p>
            <p>
              Cambios por otra unidad: <strong>{d.cambios.cantidad}</strong>
              {d.cambios.costo !== null && (
                <>
                  {' '}
                  · Costo de las unidades entregadas: <strong>{dinero(d.cambios.costo, 'PEN')}</strong>
                </>
              )}
            </p>

            {d.proveedores.length > 0 && (
              <>
                <h2>Enviados a proveedores</h2>
                <div className="marco-tabla">
                  <table className="tabla-datos">
                    <thead>
                      <tr>
                        <th>Proveedor</th>
                        <th className="num">Enviados</th>
                        <th className="num">Con respuesta</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.proveedores.map((p) => (
                        <tr key={p.proveedor}>
                          <td>{p.proveedor}</td>
                          <td className="num">{p.enviados}</td>
                          <td className="num">{p.con_respuesta}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </>
        )}
      </EstadoConsulta>

      <Avisos empresaId={empresaActivaId} />
    </main>
  )
}
