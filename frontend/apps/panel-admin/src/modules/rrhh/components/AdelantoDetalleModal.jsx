import { useState } from 'react'
import { mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Modal from '../../../shared/components/Modal'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useAdelanto, useAnularAdelanto } from '../hooks/useAdelantos'
import { fechaCorta, soles } from '../rrhh'
import '../rrhh.css'

const TONO_CUOTA = { PENDIENTE: 'ambar', DESCONTADA: 'verde', ANULADA: 'gris' }
const mesAnio = (iso) => `${iso.slice(5, 7)}/${iso.slice(0, 4)}`

/** El detalle de una entrega: sus cuotas y, con permiso, la opción de anularla. */
export default function AdelantoDetalleModal({ id, onCerrar }) {
  const { tiene } = usePermisos()
  const consulta = useAdelanto(id)
  const a = consulta.data
  const [anulando, setAnulando] = useState(false)
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')
  const anular = useAnularAdelanto(id, { exito: 'Adelanto anulado: el dinero volvió a la caja.', alExito: onCerrar })
  const hayDescontada = a?.cuotas.some((c) => c.estado === 'DESCONTADA')

  const confirmar = (evento) => {
    evento.preventDefault()
    if (anular.isPending) return
    if (!motivo.trim()) {
      setError('Indique el motivo de la anulación.')
      return
    }
    setError('')
    anular.mutate(motivo.trim(), { onError: (e) => setError(mensajeDeError(e)) })
  }

  return (
    <Modal titulo={a ? `${a.tipo_nombre} N° ${String(a.numero).padStart(6, '0')}` : 'Adelanto'} subtitulo={a?.personal_nombre} onCerrar={onCerrar} ancho={680}>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(a)}>
        {a && (
          <div className="rh-opciones">
            {a.estado === 'ANULADO' && (
              <p className="rh-aviso" role="status">
                Anulado el {fechaCorta(a.anulado_en)}. Motivo: {a.motivo_anulacion || '—'}
              </p>
            )}
            <dl className="rh-datos">
              <div>
                <dt>Entregado el</dt>
                <dd>{fechaCorta(a.fecha)}</dd>
              </div>
              <div>
                <dt>Monto</dt>
                <dd>
                  <strong>{soles(a.monto)}</strong>
                </dd>
              </div>
              <div>
                <dt>Salió de</dt>
                <dd>{a.cuenta_nombre}</dd>
              </div>
              <div>
                <dt>Método de pago</dt>
                <dd>{a.medio_pago_nombre || '—'}</dd>
              </div>
              <div>
                <dt>Falta descontar</dt>
                <dd>
                  <strong>{soles(a.saldo_pendiente)}</strong>
                </dd>
              </div>
              {a.referencia && (
                <div>
                  <dt>N° de operación</dt>
                  <dd>{a.referencia}</dd>
                </div>
              )}
              {a.motivo && (
                <div>
                  <dt>Motivo</dt>
                  <dd>{a.motivo}</dd>
                </div>
              )}
            </dl>
            <div className="marco-tabla">
              <table className="tabla-datos">
                <caption className="sr-only">Cuotas</caption>
                <thead>
                  <tr>
                    <th>Cuota</th>
                    <th>Se descuenta en</th>
                    <th>Monto</th>
                    <th>Estado</th>
                  </tr>
                </thead>
                <tbody>
                  {a.cuotas.map((c) => (
                    <tr key={c.numero}>
                      <td>{c.numero}</td>
                      <td>{mesAnio(c.periodo)}</td>
                      <td>{soles(c.monto)}</td>
                      <td>
                        <span className="pildora mas" data-tono={TONO_CUOTA[c.estado] ?? 'gris'}>
                          {c.estado_nombre}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {a.estado === 'VIGENTE' && tiene('RRHH.ADELANTOS.ANULAR') && !anulando && (
              <div className="rh-acciones">
                <button type="button" className="boton-cabecera" onClick={() => setAnulando(true)} disabled={hayDescontada} title={hayDescontada ? 'Ya se descontó una cuota en una planilla' : undefined}>
                  Anular este adelanto
                </button>
                {hayDescontada && <span className="celda-suave">Ya se descontó una cuota en una planilla: no se puede anular.</span>}
              </div>
            )}
            {anulando && (
              <form onSubmit={confirmar} noValidate className="rh-opciones">
                <p className="rh-aviso">Se anula el egreso de la caja (el dinero vuelve) y se cancelan las cuotas por descontar.</p>
                <fieldset disabled={anular.isPending} className="rh-opciones">
                  <Campo etiqueta="Motivo de la anulación" requerido error={error} contador={{ actual: motivo.length, max: 250 }}>
                    {(p) => <input {...p} maxLength={250} value={motivo} onChange={(e) => setMotivo(e.target.value)} />}
                  </Campo>
                </fieldset>
                <div className="modal-pie">
                  <button type="button" onClick={() => setAnulando(false)} disabled={anular.isPending}>
                    Volver
                  </button>
                  <button type="submit" className="primario" disabled={anular.isPending}>
                    {anular.isPending ? 'Anulando…' : 'Confirmar anulación'}
                  </button>
                </div>
              </form>
            )}
          </div>
        )}
      </EstadoConsulta>
    </Modal>
  )
}
