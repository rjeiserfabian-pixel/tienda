import { useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Modal from '../../../shared/components/Modal'
import { dinero, DENOMINACIONES, ESTADOS_SESION } from '../caja'

const fechaHora = (iso) => (iso ? new Date(iso).toLocaleString('es-PE', { dateStyle: 'short', timeStyle: 'short' }) : '—')
const detalleConteo = (conteo, moneda) =>
  DENOMINACIONES[moneda]
    .filter((d) => conteo[d])
    .map((d) => `${conteo[d]} × ${dinero(d, moneda)}`)
    .join(' · ') || 'Sin efectivo'

/** Una sesión de caja con quién la abrió y cerró, cómo cerró y todos sus conteos. */
export default function SesionDetalleModal({ sesionId, onCerrar }) {
  const consulta = useQuery({
    queryKey: ['caja', 'sesion', sesionId],
    queryFn: ({ signal }) => api.get(`/caja/sesiones/${sesionId}/`, { signal }).then((r) => r.data),
  })
  const s = consulta.data
  const estado = s && ESTADOS_SESION[s.estado]
  return (
    <Modal titulo={s ? `Sesión ${String(s.numero).padStart(6, '0')}` : 'Sesión de caja'} subtitulo={s?.cuenta_nombre} onCerrar={onCerrar} ancho={760}>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(s)}>
        {s && (
          <>
            <dl className="conteo-resumen">
              <div>
                <dt>Estado</dt>
                <dd>
                  <span className={`estado-pildora ${estado.clase}`}>{estado.texto}</span>
                </dd>
              </div>
              <div>
                <dt>Abrió</dt>
                <dd>{s.responsable_nombre}</dd>
                <dt>{fechaHora(s.abierta_en)}</dt>
              </div>
              <div>
                <dt>Cerró</dt>
                <dd>{s.cerrada_por_nombre || '—'}</dd>
                <dt>{fechaHora(s.cerrada_en)}</dt>
              </div>
              <div>
                <dt>Había al abrir</dt>
                <dd>{dinero(s.saldo_apertura, s.moneda)}</dd>
                {Number(s.fondo_entregado) > 0 && <dt>Fondo recibido {dinero(s.fondo_entregado, s.moneda)}</dt>}
              </div>
              {s.estado === 'CERRADA' ? (
                <>
                  <div>
                    <dt>Esperado</dt>
                    <dd>{dinero(s.esperado_cierre, s.moneda)}</dd>
                  </div>
                  <div>
                    <dt>Contado</dt>
                    <dd>{dinero(s.contado_cierre, s.moneda)}</dd>
                  </div>
                  <div data-tono={Number(s.diferencia) === 0 ? undefined : Number(s.diferencia) > 0 ? 'sobra' : 'falta'}>
                    <dt>Diferencia</dt>
                    <dd>{Number(s.diferencia) === 0 ? 'Cuadra' : dinero(s.diferencia, s.moneda)}</dd>
                  </div>
                </>
              ) : (
                <div>
                  <dt>Se espera ahora</dt>
                  <dd>{dinero(s.esperado_actual, s.moneda)}</dd>
                </div>
              )}
            </dl>
            {s.reaperturas > 0 && <p className="celda-suave">Se reabrió {s.reaperturas} {s.reaperturas === 1 ? 'vez' : 'veces'}.</p>}
            <h4>Conteos</h4>
            {s.arqueos.length === 0 ? (
              <p className="estado-vacio">Todavía no se contó el efectivo de esta sesión.</p>
            ) : (
              <div className="marco-tabla">
                <table className="tabla-datos">
                  <thead>
                    <tr>
                      <th>Cuándo</th>
                      <th>Quién</th>
                      <th>Clase</th>
                      <th className="num">Esperado</th>
                      <th className="num">Contado</th>
                      <th className="num">Diferencia</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.arqueos.map((a) => (
                      <tr key={a.id}>
                        <td>{fechaHora(a.creado_en)}</td>
                        <td>{a.hecho_por_nombre}</td>
                        <td className="col-texto">
                          {a.tipo_nombre}
                          <span className="sub-texto">{detalleConteo(a.conteo, s.moneda)}</span>
                          {a.observacion && <span className="sub-texto">{a.observacion}</span>}
                        </td>
                        <td className="num">{dinero(a.esperado, s.moneda)}</td>
                        <td className="num">{dinero(a.contado, s.moneda)}</td>
                        <td className={`num ${Number(a.diferencia) > 0 ? 'caja-ingreso' : Number(a.diferencia) < 0 ? 'caja-egreso' : ''}`}>{Number(a.diferencia) === 0 ? 'Cuadra' : dinero(a.diferencia, s.moneda)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </EstadoConsulta>
    </Modal>
  )
}
