import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { mensajeDeError } from '../../../core/api/client'
import BotonVolver from '../../../shared/components/BotonVolver'
import Can from '../../../shared/components/Can'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { AccionCtsModal, DepositarCtsModal } from '../components/CtsModales'
import { useAccionCts, useCts } from '../hooks/useCts'
import { fechaCorta, soles } from '../rrhh'
import '../rrhh.css'

/** Un cálculo de CTS: lo que le toca a cada trabajador, cómo se calculó y el depósito. */
export default function CtsDetallePage() {
  const { id } = useParams()
  const navegar = useNavigate()
  const consulta = useCts(id)
  const c = consulta.data
  const [modal, setModal] = useState(null) // 'depositar' | 'anular' | 'descartar'
  const [error, setError] = useState('')
  const recalcular = useAccionCts(id, 'recalcular', { exito: 'CTS recalculada.' })
  const enRevision = c?.estado === 'CALCULADO'

  return (
    <main className="listado">
      <BotonVolver ruta="/rrhh/cts" texto="CTS" />
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(c)}>
        {c && (
          <>
            <header className="rh-tarjeta">
              <header>
                <h2 style={{ margin: 0 }}>
                  CTS de {c.periodo_nombre} {c.anio}
                </h2>
                <span className="pildora mas" data-tono={enRevision ? 'ambar' : 'verde'}>
                  {enRevision ? 'En revisión' : 'Depositada'}
                </span>
              </header>
              <dl className="rh-datos">
                <div>
                  <dt>Semestre</dt>
                  <dd>
                    {fechaCorta(c.desde)} al {fechaCorta(c.hasta)}
                  </dd>
                </div>
                <div>
                  <dt>Trabajadores</dt>
                  <dd>{c.num_trabajadores}</dd>
                </div>
                <div>
                  <dt>Total a depositar</dt>
                  <dd>
                    <strong>{soles(c.total)}</strong>
                  </dd>
                </div>
                {!enRevision && (
                  <div>
                    <dt>Depositada el</dt>
                    <dd>
                      {fechaCorta(c.fecha_deposito)}
                      {c.referencia ? ` · Op. ${c.referencia}` : ''}
                    </dd>
                  </div>
                )}
              </dl>
              <div className="rh-acciones">
                {enRevision && (
                  <Can permiso="RRHH.CTS.CALCULAR">
                    <button type="button" className="boton-cabecera" disabled={recalcular.isPending} onClick={() => recalcular.mutate(undefined, { onError: (e) => setError(mensajeDeError(e)), onSuccess: () => setError('') })}>
                      {recalcular.isPending ? 'Recalculando…' : 'Recalcular'}
                    </button>
                    <button type="button" className="boton-cabecera" onClick={() => setModal('descartar')}>
                      Descartar
                    </button>
                  </Can>
                )}
                {enRevision && (
                  <Can permiso="RRHH.CTS.DEPOSITAR">
                    <button type="button" className="boton-cabecera primario" disabled={!c.puede_depositar} title={c.puede_depositar ? undefined : 'Corrija primero lo que está en rojo'} onClick={() => setModal('depositar')}>
                      Depositar
                    </button>
                  </Can>
                )}
                {!enRevision && (
                  <Can permiso="RRHH.CTS.DEPOSITAR">
                    <button type="button" className="boton-cabecera" onClick={() => setModal('anular')}>
                      Anular depósito
                    </button>
                  </Can>
                )}
              </div>
              {error && (
                <p role="alert" className="campo-error">
                  {error}
                </p>
              )}
            </header>

            <div className="marco-tabla">
              <table className="tabla-datos">
                <thead>
                  <tr>
                    <th>Trabajador</th>
                    <th className="derecha">Meses / días</th>
                    <th className="derecha">Faltas</th>
                    <th className="derecha">Rem. computable</th>
                    <th className="derecha">CTS</th>
                    <th>Revisar</th>
                  </tr>
                </thead>
                <tbody>
                  {c.trabajadores.length === 0 && <FilaVacia columnas={6} icono="users" titulo="Sin trabajadores" descripcion="No hay trabajadores con contrato en el semestre." />}
                  {c.trabajadores.map((t) => (
                    <tr key={t.id}>
                      <td>
                        <strong>{t.nombre_completo}</strong>
                        <span className="rh-sub">
                          {t.regimen_nombre} · sueldo {soles(t.sueldo)} + gratif. 1/6 {soles(t.sexto_gratificacion)}
                          {Number(t.asignacion_familiar) > 0 ? ` + asig. familiar ${soles(t.asignacion_familiar)}` : ''}
                        </span>
                      </td>
                      <td className="derecha">
                        {t.meses} / {t.dias}
                      </td>
                      <td className="derecha">{t.dias_falta}</td>
                      <td className="derecha">{soles(t.remuneracion_computable)}</td>
                      <td className="derecha">
                        <strong>{soles(t.monto)}</strong>
                      </td>
                      <td>
                        {t.avisos.map((a) => (
                          <span key={a.texto} className="rh-sub">
                            <span className="pildora" data-tono={a.nivel === 'ERROR' ? 'rojo' : 'ambar'}>
                              {a.nivel === 'ERROR' ? 'Corregir' : 'Aviso'}
                            </span>{' '}
                            {a.texto}
                          </span>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </EstadoConsulta>
      {modal === 'depositar' && c && <DepositarCtsModal cts={c} onCerrar={() => setModal(null)} />}
      {(modal === 'anular' || modal === 'descartar') && c && <AccionCtsModal cts={c} tipo={modal} onCerrar={() => setModal(null)} onListo={() => navegar('/rrhh/cts')} />}
    </main>
  )
}
