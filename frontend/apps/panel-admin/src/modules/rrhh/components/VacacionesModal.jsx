import { useState } from 'react'
import { codigoDeError, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useAnularVacaciones, useRegistrarVacaciones, useVacacionesDe } from '../hooks/useVacaciones'
import { fechaCorta, numero } from '../rrhh'
import '../rrhh.css'

const dias = (desde, hasta) => (desde && hasta ? Math.round((new Date(`${hasta}T00:00:00`) - new Date(`${desde}T00:00:00`)) / 86_400_000) + 1 : 0)

/** Registra unas vacaciones del trabajador; los días se descuentan del saldo y se marcan en la asistencia. */
function NuevaVacacion({ trabajador, onListo }) {
  const { empresaActivaId } = useEmpresas()
  const [f, setF] = useState({ desde: '', hasta: '', observacion: '', marcar: true })
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')
  const registrar = useRegistrarVacaciones({ exito: 'Vacaciones registradas.', alExito: onListo })
  const cantidad = dias(f.desde, f.hasta)

  const enviar = (evento) => {
    evento.preventDefault()
    if (registrar.isPending) return
    const e = {}
    if (!f.desde) e.desde = 'Indique el primer día.'
    if (!f.hasta) e.hasta = 'Indique el último día.'
    else if (f.desde && f.hasta < f.desde) e.hasta = 'No puede ser anterior al primer día.'
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return
    registrar.mutate(
      { empresa: empresaActivaId, personal: trabajador.personal, desde: f.desde, hasta: f.hasta, observacion: f.observacion.trim(), marcar_asistencia: f.marcar },
      {
        onSuccess: () => setF({ desde: '', hasta: '', observacion: '', marcar: true }),
        onError: (error) => {
          const delServidor = erroresDeCampo(error)
          setErrores(delServidor)
          setGeneral(Object.keys(delServidor).length > 0 && codigoDeError(error) === 'validacion' ? 'Revise los datos marcados.' : mensajeDeError(error))
        },
      },
    )
  }

  return (
    <form onSubmit={enviar} noValidate className="rh-tarjeta">
      <h3>Registrar vacaciones</h3>
      <fieldset disabled={registrar.isPending} className="rh-opciones">
        <div className="rh-fila-campos">
          <Campo etiqueta="Desde" requerido error={errores.desde}>
            {(p) => <input {...p} type="date" value={f.desde} onChange={(e) => setF({ ...f, desde: e.target.value })} />}
          </Campo>
          <Campo etiqueta="Hasta" requerido error={errores.hasta} ayuda={cantidad > 0 ? `${cantidad} día(s) corridos` : undefined}>
            {(p) => <input {...p} type="date" value={f.hasta} min={f.desde || undefined} onChange={(e) => setF({ ...f, hasta: e.target.value })} />}
          </Campo>
          <Campo etiqueta="Observación" contador={{ actual: f.observacion.length, max: 150 }}>
            {(p) => <input {...p} maxLength={150} value={f.observacion} onChange={(e) => setF({ ...f, observacion: e.target.value })} />}
          </Campo>
        </div>
        <label className="rh-check">
          <input type="checkbox" checked={f.marcar} onChange={(e) => setF({ ...f, marcar: e.target.checked })} />
          Marcar estos días como vacaciones en la asistencia (déjalo sin marcar para vacaciones antiguas)
        </label>
      </fieldset>
      {general && (
        <p role="alert" className="campo-error">
          {general}
        </p>
      )}
      <div className="rh-acciones">
        <button type="submit" className="boton-cabecera primario" disabled={registrar.isPending}>
          {registrar.isPending ? 'Registrando…' : 'Registrar'}
        </button>
      </div>
    </form>
  )
}

/** Las vacaciones de un trabajador: su saldo, lo que ya tomó y, con permiso, registrar o anular. */
export default function VacacionesModal({ trabajador, onCerrar }) {
  const { empresaActivaId } = useEmpresas()
  const { tiene } = usePermisos()
  const historial = useVacacionesDe(empresaActivaId, trabajador.personal)
  const [anulando, setAnulando] = useState(null)
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')
  const anular = useAnularVacaciones({ exito: 'Vacaciones anuladas: los días volvieron al saldo.', alExito: () => setAnulando(null) })

  const confirmar = (evento) => {
    evento.preventDefault()
    if (anular.isPending) return
    if (!motivo.trim()) return setError('Indique el motivo de la anulación.')
    setError('')
    return anular.mutate({ id: anulando, motivo: motivo.trim() }, { onError: (e) => setError(mensajeDeError(e)) })
  }

  return (
    <Modal titulo={trabajador.nombre_completo} subtitulo="Vacaciones" onCerrar={onCerrar} ancho={780}>
      <div className="rh-opciones">
        <dl className="rh-datos">
          <div>
            <dt>Servicio desde</dt>
            <dd>
              {fechaCorta(trabajador.inicio_servicio)} ({trabajador.meses_servicio} meses)
            </dd>
          </div>
          <div>
            <dt>Días al año</dt>
            <dd>{trabajador.dias_anuales}</dd>
          </div>
          <div>
            <dt>Ganados / tomados</dt>
            <dd>
              {numero(trabajador.ganados)} / {trabajador.tomados}
            </dd>
          </div>
          <div>
            <dt>Saldo</dt>
            <dd>
              <strong>{numero(trabajador.saldo)} días</strong>
            </dd>
          </div>
        </dl>

        <EstadoConsulta consulta={historial} hayDatos={Boolean(historial.data)}>
          {historial.data && historial.data.results.length === 0 && <p className="celda-suave">Todavía no tiene vacaciones registradas.</p>}
          {historial.data && historial.data.results.length > 0 && (
            <div className="marco-tabla">
              <table className="tabla-datos">
                <caption className="sr-only">Vacaciones registradas</caption>
                <thead>
                  <tr>
                    <th>Del</th>
                    <th>Al</th>
                    <th className="derecha">Días</th>
                    <th>Estado</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {historial.data.results.map((v) => (
                    <tr key={v.id}>
                      <td>{fechaCorta(v.desde)}</td>
                      <td>{fechaCorta(v.hasta)}</td>
                      <td className="derecha">{v.dias}</td>
                      <td>
                        <span className="pildora mas" data-tono={v.estado === 'ANULADA' ? 'gris' : 'verde'}>
                          {v.estado_nombre}
                        </span>
                        {v.observacion && <span className="rh-sub">{v.observacion}</span>}
                      </td>
                      <td className="derecha">
                        {v.estado === 'REGISTRADA' && tiene('RRHH.VACACIONES.ANULAR') && (
                          <button type="button" className="boton-cabecera" onClick={() => { setAnulando(v.id); setMotivo(''); setError('') }}>
                            Anular
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </EstadoConsulta>

        {anulando && (
          <form onSubmit={confirmar} noValidate className="rh-tarjeta">
            <p className="rh-aviso">Los días vuelven al saldo y se quitan de la asistencia (si la planilla del mes está cerrada, primero hay que reabrirla).</p>
            <fieldset disabled={anular.isPending} className="rh-opciones">
              <Campo etiqueta="Motivo de la anulación" requerido error={error} contador={{ actual: motivo.length, max: 250 }}>
                {(p) => <input {...p} maxLength={250} value={motivo} onChange={(e) => setMotivo(e.target.value)} />}
              </Campo>
            </fieldset>
            <div className="rh-acciones">
              <button type="button" className="boton-cabecera" onClick={() => setAnulando(null)} disabled={anular.isPending}>
                Volver
              </button>
              <button type="submit" className="boton-cabecera primario" disabled={anular.isPending}>
                {anular.isPending ? 'Anulando…' : 'Confirmar anulación'}
              </button>
            </div>
          </form>
        )}

        {tiene('RRHH.VACACIONES.REGISTRAR') && <NuevaVacacion trabajador={trabajador} onListo={() => setAnulando(null)} />}
      </div>
    </Modal>
  )
}
