import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useTurnosToma } from '../hooks/useToma'
import { fechaCorta, hoyIso } from '../inventario'
import { horaActual, TURNOS } from '../tomas'
import '../tomas.css'

const hora = (texto) => (texto ? String(texto).slice(0, 5) : '—')

function TurnoModal({ tomaId, onCerrar, onCreado }) {
  const [f, setF] = useState({ fecha: hoyIso(), turno: 'MANANA', horaInicio: horaActual(), equipo: '' })
  const [errores, setErrores] = useState({})
  const crear = useMutacion({
    mutationFn: (cuerpo) => api.post(`/inventario/tomas/${tomaId}/turnos/nuevo/`, cuerpo).then((r) => r.data),
    invalidar: [['tomas', 'turnos', tomaId]],
    exito: 'Turno iniciado.',
    alExito: (turno) => {
      onCreado(turno)
      onCerrar()
    },
    avisarError: false,
  })
  const poner = (campo, valor) => setF((previo) => ({ ...previo, [campo]: valor }))

  const enviar = (evento) => {
    evento.preventDefault()
    if (crear.isPending) return
    const e = {}
    if (!f.fecha) e.fecha = 'Indique la fecha.'
    if (!f.horaInicio) e.hora_inicio = 'Indique la hora de inicio.'
    setErrores(e)
    if (Object.keys(e).length) return
    crear.mutate(
      { fecha: f.fecha, turno: f.turno, hora_inicio: f.horaInicio, equipo: f.equipo.trim() },
      { onError: (error) => setErrores({ ...erroresDeCampo(error), general: mensajeDeError(error) }) },
    )
  }

  return (
    <Modal titulo="Iniciar un turno" subtitulo="Deja constancia de cuándo y quiénes cuentan." onCerrar={onCerrar} ancho={520}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={crear.isPending} className="toma-fieldset">
          <div className="fila-campos">
            <Campo etiqueta="Fecha" icono="calendario" requerido error={errores.fecha}>
              {(p) => <input {...p} type="date" value={f.fecha} onChange={(e) => poner('fecha', e.target.value)} />}
            </Campo>
            <Campo etiqueta="Turno" tipo="select" requerido error={errores.turno}>
              {(p) => (
                <select {...p} value={f.turno} onChange={(e) => poner('turno', e.target.value)}>
                  {Object.entries(TURNOS).map(([valor, texto]) => (
                    <option key={valor} value={valor}>
                      {texto}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Hora de inicio" icono="reloj" requerido error={errores.hora_inicio}>
              {(p) => <input {...p} type="time" value={f.horaInicio} onChange={(e) => poner('horaInicio', e.target.value)} />}
            </Campo>
          </div>
          <Campo etiqueta="Quiénes cuentan" error={errores.equipo}>
            {(p) => <input {...p} maxLength={200} placeholder="Opcional. Ej. Ana, Luis" value={f.equipo} onChange={(e) => poner('equipo', e.target.value)} />}
          </Campo>
        </fieldset>
        {errores.general && !errores.fecha && !errores.hora_inicio && (
          <p role="alert" className="campo-error">
            {errores.general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={crear.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={crear.isPending}>
            {crear.isPending ? 'Iniciando…' : 'Iniciar turno'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

/**
 * Turnos de la toma y cuál está en curso. El turno elegido se anota en cada conteo, así queda
 * claro quién contó qué y en qué horario.
 */
export default function TomaTurnos({ tomaId, turnoActivo, onTurno }) {
  const [iniciando, setIniciando] = useState(false)
  const turnos = useTurnosToma(tomaId)
  const lista = turnos.data ?? []

  const finalizar = useMutacion({
    mutationFn: (turno) => api.post(`/inventario/tomas/${tomaId}/turnos/${turno}/finalizar/`, { hora_fin: horaActual() }).then((r) => r.data),
    invalidar: [['tomas', 'turnos', tomaId]],
    exito: 'Turno finalizado.',
    alExito: (_, turno) => {
      if (String(turno) === String(turnoActivo)) onTurno('') // ya no se sigue contando en ese turno
    },
  })

  const abiertos = lista.filter((t) => !t.hora_fin)

  return (
    <section className="toma-panel" aria-label="Turnos de conteo">
      <header className="toma-panel-cabecera">
        <h3>Turnos</h3>
        <button type="button" onClick={() => setIniciando(true)}>
          <Icono nombre="agregar" tam={17} /> Iniciar turno
        </button>
      </header>

      {turnos.isLoading && <p className="celda-suave">Cargando turnos…</p>}
      {turnos.isError && (
        <p role="alert" className="campo-error">
          {mensajeDeError(turnos.error)}
        </p>
      )}
      {turnos.isSuccess && lista.length === 0 && <p className="celda-suave">Aún no hay turnos. Inicia uno para dejar constancia de quién cuenta y en qué horario (es opcional).</p>}

      {abiertos.length > 0 && (
        <Campo etiqueta="Contando en el turno" tipo="select">
          {(p) => (
            <select {...p} value={turnoActivo} onChange={(e) => onTurno(e.target.value)}>
              <option value="">Sin turno</option>
              {abiertos.map((t) => (
                <option key={t.id} value={t.id}>
                  {fechaCorta(t.fecha)} · {t.turno_nombre} desde {hora(t.hora_inicio)}
                  {t.equipo ? ` · ${t.equipo}` : ''}
                </option>
              ))}
            </select>
          )}
        </Campo>
      )}

      {lista.length > 0 && (
        <ul className="toma-turnos">
          {lista.map((t) => (
            <li key={t.id}>
              <span>
                <strong>{fechaCorta(t.fecha)}</strong> · {t.turno_nombre} · {hora(t.hora_inicio)} – {hora(t.hora_fin)}
                {t.equipo && <span className="sub-texto">{t.equipo}</span>}
              </span>
              {t.hora_fin ? (
                <span className="pildora" data-tono="gris">
                  Finalizado
                </span>
              ) : (
                <button type="button" disabled={finalizar.isPending} onClick={() => finalizar.mutate(t.id)}>
                  {finalizar.isPending && finalizar.variables === t.id ? 'Finalizando…' : 'Finalizar'}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {iniciando && <TurnoModal tomaId={tomaId} onCerrar={() => setIniciando(false)} onCreado={(turno) => onTurno(String(turno.id))} />}
    </section>
  )
}
