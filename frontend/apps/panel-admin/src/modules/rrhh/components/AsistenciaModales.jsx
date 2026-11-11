import { useState } from 'react'
import { codigoDeError, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useAccionAsistencia } from '../hooks/useAsistencia'
import { decimal, decimalValido, fechaCorta } from '../rrhh'
import '../rrhh.css'

function errorDelServidor(error, poner, ponerGeneral) {
  const delServidor = erroresDeCampo(error)
  poner(delServidor)
  const conCampos = Object.keys(delServidor).length > 0 && codigoDeError(error) === 'validacion'
  ponerGeneral(conCampos ? 'Revise los datos marcados.' : mensajeDeError(error))
}

function Pie({ general, enviando, textoEnviar, textoEnviando, onCerrar, extra }) {
  return (
    <>
      {general && (
        <p role="alert" className="campo-error">
          {general}
        </p>
      )}
      <div className="modal-pie">
        {extra}
        <button type="button" onClick={onCerrar} disabled={enviando}>
          Cancelar
        </button>
        <button type="submit" className="primario" disabled={enviando}>
          {enviando ? textoEnviando : textoEnviar}
        </button>
      </div>
    </>
  )
}

/** Marca (o corrige, o borra) UN día de un trabajador. */
export function MarcaModal({ empresa, trabajador, dia, marca, tipos, onCerrar }) {
  const [tipo, setTipo] = useState(() => tipos.find((t) => t.codigo === marca?.tipo)?.id ?? '')
  const [horas, setHoras] = useState(marca?.horas_extra && Number(marca.horas_extra) > 0 ? String(Number(marca.horas_extra)) : '')
  const [observacion, setObservacion] = useState(marca?.observacion ?? '')
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')
  const accion = useAccionAsistencia('dia', { exito: 'Asistencia guardada.', alExito: onCerrar })
  const elegido = tipos.find((t) => t.id === tipo)

  const enviar = (tipoFinal) => {
    if (accion.isPending) return
    const e = {}
    if (tipoFinal !== null && !tipoFinal) e.tipo = 'Elija qué se marca ese día.'
    const t = tipos.find((x) => x.id === tipoFinal)
    if (horas && (!decimalValido(horas, 12) || Number(horas) <= 0)) e.horas_extra = 'De 0 a 12 horas.'
    else if (horas && t && !t.cuenta_dia_laborado) e.horas_extra = 'Solo un día trabajado puede tener horas extra.'
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return
    accion.mutate(
      { empresa, personal: trabajador.id, fecha: dia.fecha, tipo: tipoFinal, horas_extra: tipoFinal && horas ? horas : '0', observacion: observacion.trim() },
      { onError: (error) => errorDelServidor(error, setErrores, setGeneral) },
    )
  }

  return (
    <Modal titulo={`Asistencia del ${fechaCorta(dia.fecha)}`} subtitulo={trabajador.nombre_completo} onCerrar={onCerrar}>
      <form
        onSubmit={(evento) => {
          evento.preventDefault()
          enviar(tipo)
        }}
        noValidate
      >
        <fieldset disabled={accion.isPending} className="rh-opciones">
          {dia.feriado && <p className="rh-aviso">Feriado: {dia.feriado}.</p>}
          <div className="rh-tipos" role="radiogroup" aria-label="Qué se marca">
            {tipos.map((t) => (
              <button key={t.id} type="button" role="radio" aria-checked={tipo === t.id} className="rh-tipo" data-cat={t.categoria} onClick={() => setTipo(t.id)}>
                <strong>{t.codigo}</strong>
                <span>{t.nombre}</span>
              </button>
            ))}
          </div>
          {errores.tipo && (
            <p role="alert" className="campo-error">
              {errores.tipo}
            </p>
          )}
          <div className="rh-fila-campos">
            <Campo etiqueta="Horas extra" error={errores.horas_extra} ayuda={elegido && !elegido.cuenta_dia_laborado ? 'Este tipo no es un día trabajado.' : 'Opcional, de 0 a 12.'}>
              {(p) => <input {...p} inputMode="decimal" value={horas} onChange={(e) => setHoras(decimal(e.target.value))} />}
            </Campo>
            <Campo etiqueta="Observación" error={errores.observacion} contador={{ actual: observacion.length, max: 100 }}>
              {(p) => <input {...p} maxLength={100} placeholder="Opcional" value={observacion} onChange={(e) => setObservacion(e.target.value)} />}
            </Campo>
          </div>
        </fieldset>
        <Pie
          general={general}
          enviando={accion.isPending}
          textoEnviar="Guardar"
          textoEnviando="Guardando…"
          onCerrar={onCerrar}
          extra={
            marca && (
              <button type="button" onClick={() => enviar(null)} disabled={accion.isPending}>
                Quitar la marca
              </button>
            )
          }
        />
      </form>
    </Modal>
  )
}

/** Marca varios días seguidos de un trabajador (vacaciones, descanso médico, permisos…). */
export function RangoModal({ empresa, mes, anio, trabajadores, tipos, onCerrar }) {
  const primero = `${anio}-${String(mes).padStart(2, '0')}-01`
  const [personal, setPersonal] = useState('')
  const [desde, setDesde] = useState(primero)
  const [hasta, setHasta] = useState(primero)
  const [tipo, setTipo] = useState('')
  const [sobrescribir, setSobrescribir] = useState(false)
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')
  const accion = useAccionAsistencia('rango', {
    exito: (datos) => `Se marcaron ${datos.marcados} día(s).`,
    alExito: onCerrar,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (accion.isPending) return
    const e = {}
    if (!personal) e.personal = 'Elija el trabajador.'
    if (!desde) e.desde = 'Indique el primer día.'
    if (!hasta) e.hasta = 'Indique el último día.'
    else if (desde && hasta < desde) e.hasta = 'No puede ser anterior al primer día.'
    if (!tipo) e.tipo = 'Elija qué se marca.'
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return
    accion.mutate(
      { empresa, personal: Number(personal), desde, hasta, tipo: Number(tipo), sobrescribir },
      { onError: (error) => errorDelServidor(error, setErrores, setGeneral) },
    )
  }

  return (
    <Modal titulo="Marcar varios días" subtitulo="Para vacaciones, descansos médicos o permisos de varios días seguidos." onCerrar={onCerrar} ancho={640}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={accion.isPending} className="rh-opciones">
          <Campo etiqueta="Trabajador" tipo="select" requerido error={errores.personal}>
            {(p) => (
              <select {...p} value={personal} onChange={(e) => setPersonal(e.target.value)}>
                <option value="">Elegir trabajador</option>
                {trabajadores.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.nombre_completo}
                  </option>
                ))}
              </select>
            )}
          </Campo>
          <div className="rh-fila-campos">
            <Campo etiqueta="Desde" requerido error={errores.desde}>
              {(p) => <input {...p} type="date" value={desde} onChange={(e) => setDesde(e.target.value)} />}
            </Campo>
            <Campo etiqueta="Hasta" requerido error={errores.hasta} ayuda="Hasta 62 días.">
              {(p) => <input {...p} type="date" value={hasta} onChange={(e) => setHasta(e.target.value)} />}
            </Campo>
          </div>
          <Campo etiqueta="Qué se marca" tipo="select" requerido error={errores.tipo}>
            {(p) => (
              <select {...p} value={tipo} onChange={(e) => setTipo(e.target.value)}>
                <option value="">Elegir tipo</option>
                {tipos.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.codigo} · {t.nombre}
                  </option>
                ))}
              </select>
            )}
          </Campo>
          <label className="rh-check">
            <input type="checkbox" checked={sobrescribir} onChange={(e) => setSobrescribir(e.target.checked)} />
            Reemplazar también los días que ya tienen una marca
          </label>
          <p className="celda-suave">Los días en que el trabajador no tenía contrato se saltan.</p>
        </fieldset>
        <Pie general={general} enviando={accion.isPending} textoEnviar="Marcar días" textoEnviando="Marcando…" onCerrar={onCerrar} />
      </form>
    </Modal>
  )
}

const DESCANSOS = [
  ['DOMINGO', 'Solo el domingo'],
  ['SABADO_DOMINGO', 'Sábado y domingo'],
]

/** Rellena los días VACÍOS del mes: feriados, descansos y asistencia. Nunca pisa lo ya marcado. */
export function CompletarModal({ empresa, mes, anio, nombreMes, onCerrar }) {
  const [descanso, setDescanso] = useState('DOMINGO')
  const [general, setGeneral] = useState('')
  const accion = useAccionAsistencia('completar', {
    exito: (datos) => `Se marcaron ${datos.dias} día(s) de ${datos.trabajadores} trabajador(es).`,
    alExito: onCerrar,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (accion.isPending) return
    setGeneral('')
    accion.mutate({ empresa, anio, mes, descanso }, { onError: (error) => setGeneral(mensajeDeError(error)) })
  }

  return (
    <Modal titulo={`Completar ${nombreMes} ${anio}`} subtitulo="Ahorra marcar día por día." onCerrar={onCerrar}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={accion.isPending} className="rh-opciones">
          <p className="rh-aviso">
            Se rellenan solo los días <strong>vacíos</strong> de cada trabajador con contrato: feriado → FER, día de descanso → DS y los demás → A (asistió). Lo que ya marcó no se toca. Después corrija a mano las faltas, vacaciones o descansos médicos.
          </p>
          <div className="segmentos" role="radiogroup" aria-label="Descanso semanal">
            {DESCANSOS.map(([valor, texto]) => (
              <button key={valor} type="button" role="radio" aria-checked={descanso === valor} className={descanso === valor ? 'activo' : undefined} onClick={() => setDescanso(valor)}>
                {texto}
              </button>
            ))}
          </div>
        </fieldset>
        <Pie general={general} enviando={accion.isPending} textoEnviar="Completar el mes" textoEnviando="Completando…" onCerrar={onCerrar} />
      </form>
    </Modal>
  )
}
