import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../../core/api/client'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Can from '../../../shared/components/Can'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { hoyIso } from '../../almacen/inventario'
import { ATAJOS_RANGO } from '../../almacen/reportes'
import { Rango } from '../../caja/components/ReporteComun'
import { dinero } from '../../compras/compras'
import ComisionesModal from '../components/ComisionesModal'
import ReporteUtilidad from '../components/ReporteUtilidad'
import { ESTADOS_ORDEN } from '../servicio'
import '../../almacen/inventario.css'
import '../../compras/compras.css'
import '../../caja/caja.css'
import '../servicio-tecnico.css'

const dias = (valor) => (valor === null || valor === undefined ? '—' : `${valor} d`)

/** Revisa el periodo antes de pedirlo (el servidor admite hasta 366 días y no acepta fechas futuras). */
function revisar({ desde, hasta }) {
  if (!desde || !hasta) return 'Indica desde y hasta.'
  if (desde > hasta) return '«Desde» no puede ser posterior a «Hasta».'
  if ((new Date(hasta) - new Date(desde)) / 86_400_000 > 366) return 'El periodo no puede pasar de un año.'
  if (hasta > hoyIso()) return '«Hasta» no puede ser una fecha futura.'
  return ''
}

function Tarjetas({ r }) {
  return (
    <dl className="cxp-tarjetas" aria-label="Resumen del periodo">
      <div>
        <dt>Equipos recibidos</dt>
        <dd>{r.ingresadas}</dd>
      </div>
      <div>
        <dt>Equipos entregados</dt>
        <dd>{r.entregadas}</dd>
      </div>
      <div>
        <dt>Tiempo promedio ingreso → entrega</dt>
        <dd>{dias(r.ciclo_promedio_dias)}</dd>
      </div>
      <div>
        <dt>Abiertas ahora</dt>
        <dd>{r.abiertas}</dd>
      </div>
      <div data-tono={r.atrasadas > 0 ? 'rojo' : undefined}>
        <dt>Atrasadas</dt>
        <dd>{r.atrasadas}</dd>
      </div>
      <div data-tono={r.por_abandonar > 0 ? 'ambar' : undefined}>
        <dt>Por abandonar</dt>
        <dd>{r.por_abandonar}</dd>
      </div>
      <div>
        <dt>Reingresos por garantía</dt>
        <dd>{r.reingresos_garantia}</dd>
        <small>{r.reingresos_sobre_entregadas === null ? '—' : `${r.reingresos_sobre_entregadas}% de lo entregado`}</small>
      </div>
    </dl>
  )
}

function Estados({ resumen, tiempos }) {
  const tiempo = Object.fromEntries(tiempos.estados.map((e) => [e.estado, e]))
  return (
    <section aria-label="Estados y tiempos">
      <h3>Cuánto tarda cada estado</h3>
      <div className="marco-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th>Estado</th>
              <th className="num">Abiertas ahora</th>
              <th className="num">Días promedio</th>
              <th className="num">Veces</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(ESTADOS_ORDEN).map(([estado, e]) => {
              const abiertas = resumen.por_estado.find((x) => x.estado === estado)?.cantidad ?? 0
              const t = tiempo[estado]
              if (!abiertas && !t) return null
              return (
                <tr key={estado}>
                  <td>
                    <span className="pildora" data-tono={e.tono}>
                      {e.texto}
                    </span>
                  </td>
                  <td className="num">{abiertas || '—'}</td>
                  <td className="num">{t ? t.dias_promedio : '—'}</td>
                  <td className="num">{t ? t.veces : '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {tiempos.truncado && <p className="celda-suave">Hay muchas órdenes en el periodo: los tiempos se calcularon con una parte. Acorta el periodo para más exactitud.</p>}
    </section>
  )
}

function Tecnicos({ lista, conImportes, onComisiones }) {
  return (
    <section aria-label="Técnicos">
      <div className="servicio-seccion-titulo">
        <h3>Técnicos</h3>
        <Can permiso="SERVICIOS.COMISIONES.GESTIONAR">
          <button type="button" className="boton-cabecera" onClick={onComisiones}>
            Fijar comisiones
          </button>
        </Can>
      </div>
      <div className="marco-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th>Técnico</th>
              <th className="num">Abiertas</th>
              <th className="num">Entregadas</th>
              <th className="num">Días promedio</th>
              <th className="num">Reingresos</th>
              {conImportes && <th className="num">Mano de obra</th>}
              {conImportes && <th className="num">%</th>}
              {conImportes && <th className="num">Comisión</th>}
            </tr>
          </thead>
          <tbody>
            {lista.length === 0 && (
              <tr>
                <td colSpan={conImportes ? 8 : 5} className="estado-vacio">
                  No hay técnicos en esta empresa.
                </td>
              </tr>
            )}
            {lista.map((t) => (
              <tr key={t.id}>
                <td>
                  {t.nombre}
                  {!t.tiene_usuario && <span className="sub-texto">Sin usuario</span>}
                </td>
                <td className="num">{t.abiertas}</td>
                <td className="num">{t.entregadas}</td>
                <td className="num">{dias(t.ciclo_promedio_dias)}</td>
                <td className="num">{t.reingresos}</td>
                {conImportes && <td className="num">{dinero(t.mano_obra)}</td>}
                {conImportes && <td className="num">{Number(t.porcentaje)}%</td>}
                {conImportes && <td className="num">{dinero(t.comision)}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function Repetidos({ datos }) {
  if (datos.equipos.length === 0 && datos.modelos.length === 0) return null
  return (
    <section aria-label="Equipos que más vuelven">
      <h3>Equipos que más vuelven</h3>
      {datos.equipos.length > 0 && (
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Equipo</th>
                <th>Cliente</th>
                <th className="num">Ingresos</th>
              </tr>
            </thead>
            <tbody>
              {datos.equipos.map((e) => (
                <tr key={e.equipo}>
                  <td>
                    {[e.tipo, e.marca, e.modelo].filter(Boolean).join(' ')}
                    {e.numero_serie && <span className="sub-texto">Serie {e.numero_serie}</span>}
                  </td>
                  <td>{e.cliente}</td>
                  <td className="num">{e.ingresos}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {datos.modelos.length > 0 && (
        <>
          <h4>Marcas y modelos con más ingresos</h4>
          <div className="marco-tabla">
            <table className="tabla-datos">
              <thead>
                <tr>
                  <th>Marca y modelo</th>
                  <th className="num">Ingresos</th>
                </tr>
              </thead>
              <tbody>
                {datos.modelos.map((m) => (
                  <tr key={`${m.tipo}-${m.marca}-${m.modelo}`}>
                    <td>{[m.tipo, m.marca, m.modelo].filter(Boolean).join(' ')}</td>
                    <td className="num">{m.ingresos}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}

/** Cómo va el taller en un periodo: cantidades, tiempos, técnicos, equipos que vuelven y utilidad. */
export default function ReportesServicioPage() {
  const { empresaActivaId } = useEmpresas()
  const [rango, setRango] = useState(() => ATAJOS_RANGO[0].rango())
  const [comisiones, setComisiones] = useState(false)
  const pendiente = revisar(rango)
  const consulta = useQuery({
    queryKey: ['servicio', 'reporte', empresaActivaId, rango],
    queryFn: ({ signal }) => api.get('/servicio-tecnico/reportes/resumen/', { params: { empresa: empresaActivaId, ...rango }, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId) && !pendiente,
    staleTime: 30_000,
    retry: false,
  })
  const d = consulta.data

  return (
    <main className="listado">
      <CabeceraListado icono="chart" titulo="Reportes del taller" descripcion="Cuántos equipos entran y salen, cuánto tarda cada paso, quién rinde y cuánto deja cada servicio. Los importes los ve quien tiene permiso para ver la utilidad." />
      <section className="reporte-caja" aria-label="Periodo">
        <div className="panel-reportes">
          <Rango rango={rango} setRango={setRango} />
          {pendiente && <p className="celda-suave">{pendiente}</p>}
        </div>
      </section>
      {!pendiente && (
        <EstadoConsulta consulta={consulta} hayDatos={Boolean(d)}>
          {d && (
            <>
              <Tarjetas r={d.resumen} />
              <Estados resumen={d.resumen} tiempos={d.tiempos} />
              <Tecnicos lista={d.tecnicos} conImportes={d.con_importes} onComisiones={() => setComisiones(true)} />
              <Repetidos datos={d.repetidos} />
              {d.con_importes && d.utilidad && <ReporteUtilidad empresa={empresaActivaId} rango={rango} utilidad={d.utilidad} />}
            </>
          )}
        </EstadoConsulta>
      )}
      {comisiones && <ComisionesModal empresa={empresaActivaId} onCerrar={() => setComisiones(false)} />}
    </main>
  )
}
