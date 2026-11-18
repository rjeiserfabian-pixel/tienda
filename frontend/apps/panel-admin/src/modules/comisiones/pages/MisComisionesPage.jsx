import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { hoyIso } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import '../../almacen/inventario.css'
import '../../compras/compras.css'

const pct = (p) => `${String(Number(p)).replace('.', ',')} %`
const ESTADOS = { PENDIENTE: 'Por pagar', EN_PLANILLA: 'En la planilla', PAGADA_APARTE: 'Pagada', SIN_MONTO: 'Nada que pagar' }

function Tarjeta({ titulo, valor, nota }) {
  return (
    <div>
      <dt>{titulo}</dt>
      <dd>{valor}</dd>
      {nota && <small>{nota}</small>}
    </div>
  )
}

/** «Mis comisiones»: lo que llevo ganado, cómo voy en mi meta y mi lugar entre los vendedores. */
export default function MisComisionesPage() {
  const { empresaActivaId } = useEmpresas()
  const hoy = hoyIso().slice(0, 7)
  const [mes, setMes] = useState(hoy)
  const consulta = useQuery({
    queryKey: ['comisiones', 'mias', empresaActivaId, mes],
    queryFn: ({ signal }) => api.get('/comisiones/mias/', { params: { empresa: empresaActivaId, mes }, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId && mes),
  })
  const d = consulta.data
  return (
    <main className="listado">
      <CabeceraListado icono="coins" titulo="Mis comisiones" descripcion="Lo que llevas ganado este mes, cómo vas con tu meta y tu lugar entre los vendedores." />
      <Campo etiqueta="Mes">{(props) => <input {...props} type="month" value={mes} max={hoy} onChange={(e) => setMes(e.target.value)} />}</Campo>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(d)}>
        {d && (
          <>
            <dl className="cxp-tarjetas" aria-label="Lo que llevas ganado">
              <Tarjeta titulo="Comisión por ventas" valor={dinero(d.ganado_hasta_hoy.ventas, 'PEN')} nota="Lo que ya cobraste de tus ventas" />
              <Tarjeta titulo="Comisión por servicios" valor={dinero(d.ganado_hasta_hoy.servicios, 'PEN')} nota="Como técnico, por la mano de obra" />
              <Tarjeta titulo="Vendido en el mes" valor={dinero(d.avance.ventas, 'PEN')} nota="Sin IGV, menos devoluciones" />
              <Tarjeta titulo="Mi lugar" valor={d.ranking.posicion ? `${d.ranking.posicion}.º de ${d.ranking.de}` : '—'} nota="Entre los vendedores del mes" />
            </dl>
            <p className="celda-suave">{d.ganado_hasta_hoy.nota}</p>

            {d.avance.escala && (
              <section>
                <h2>Mi escala</h2>
                <p>
                  Hoy ganas <strong>{d.avance.escala.porcentaje ? pct(d.avance.escala.porcentaje) : '—'}</strong> en lo que vendes sin una regla propia del producto.
                  {d.avance.escala.siguiente && ` Te faltan ${dinero(d.avance.escala.siguiente.falta, 'PEN')} para subir al ${pct(d.avance.escala.siguiente.porcentaje)}.`}
                </p>
              </section>
            )}

            {d.avance.metas.length > 0 && (
              <section>
                <h2>Mis metas</h2>
                <ul>
                  {d.avance.metas.map((m) => (
                    <li key={m.id}>
                      <strong>{m.nombre}:</strong> {m.cumplida ? `¡cumplida! Bono de ${dinero(m.bono, 'PEN')}` : `te faltan ${dinero(m.falta, 'PEN')} para ganar ${dinero(m.bono, 'PEN')}`}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {d.ranking.top.length > 0 && (
              <section>
                <h2>Ranking de ventas del mes</h2>
                <ol>
                  {d.ranking.top.map((r) => (
                    <li key={r.nombre}>
                      {r.soy_yo ? <strong>{r.nombre} (yo)</strong> : r.nombre}: {dinero(r.ventas, 'PEN')}
                    </li>
                  ))}
                </ol>
              </section>
            )}

            <section>
              <h2>Mis meses cerrados</h2>
              <div className="marco-tabla">
                <table className="tabla-datos">
                  <thead>
                    <tr>
                      <th>Mes</th>
                      <th className="num">Ventas</th>
                      <th className="num">Bonos</th>
                      <th className="num">Servicios</th>
                      <th className="num">A pagar</th>
                      <th>Estado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.liquidaciones.length === 0 && (
                      <tr>
                        <td colSpan={6} className="celda-suave">
                          Aún no hay meses cerrados.
                        </td>
                      </tr>
                    )}
                    {d.liquidaciones.map((l) => (
                      <tr key={l.id}>
                        <td>{l.periodo}</td>
                        <td className="num">{dinero(l.comisiones_ventas, 'PEN')}</td>
                        <td className="num">{dinero(l.bonos, 'PEN')}</td>
                        <td className="num">{dinero(l.comisiones_tecnico, 'PEN')}</td>
                        <td className="num">
                          <strong>{dinero(l.a_pagar, 'PEN')}</strong>
                        </td>
                        <td>{ESTADOS[l.estado] ?? l.estado}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        )}
      </EstadoConsulta>
    </main>
  )
}
