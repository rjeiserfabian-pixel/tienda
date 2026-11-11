import { useState } from 'react'
import { codigoDeError, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useAccionContrato, useCrearContrato, useEditarContrato, useRegimenes } from '../hooks/useTrabajadores'
import { decimal, decimalValido, soles } from '../rrhh'
import '../rrhh.css'

const TIPOS_CONTRATO = [
  ['INDETERMINADO', 'A plazo indeterminado'],
  ['PLAZO_FIJO', 'A plazo fijo'],
  ['TIEMPO_PARCIAL', 'A tiempo parcial'],
  ['PRACTICAS', 'Prácticas'],
  ['OTRO', 'Otro'],
]
const CATEGORIAS = [
  ['EMPLEADO', 'Empleado'],
  ['OBRERO', 'Obrero'],
  ['EJECUTIVO', 'Ejecutivo'],
]

const hoy = () => new Date().toLocaleDateString('en-CA') // AAAA-MM-DD en la hora local

/** Muestra el error del servidor: por campo si lo hay, y si no un mensaje general. */
function errorDelServidor(error, poner, ponerGeneral) {
  const delServidor = erroresDeCampo(error)
  poner(delServidor)
  const conCampos = Object.keys(delServidor).length > 0 && codigoDeError(error) === 'validacion'
  ponerGeneral(conCampos ? 'Revise los datos marcados.' : mensajeDeError(error))
}

/** Pie común de los formularios: error general y botones (se deshabilitan mientras se envía). */
function Pie({ general, enviando, textoEnviar, textoEnviando, onCerrar, deshabilitar }) {
  return (
    <>
      {general && (
        <p role="alert" className="campo-error">
          {general}
        </p>
      )}
      <div className="modal-pie">
        <button type="button" onClick={onCerrar} disabled={enviando}>
          Cancelar
        </button>
        <button type="submit" className="primario" disabled={enviando || deshabilitar}>
          {enviando ? textoEnviando : textoEnviar}
        </button>
      </div>
    </>
  )
}

/**
 * Contrato nuevo (con su sueldo inicial) o corrección de uno vigente. Al corregir no se tocan el
 * inicio ni el sueldo: eso rompería el historial (el sueldo se cambia con «Cambiar sueldo»).
 */
export function ContratoModal({ trabajador, contrato, verSueldos, onCerrar, onAviso }) {
  const editando = Boolean(contrato)
  const regimenes = useRegimenes()
  const [f, setF] = useState({
    regimen: contrato?.regimen ? String(contrato.regimen) : '',
    tipo_contrato: contrato?.tipo_contrato ?? 'INDETERMINADO',
    categoria: contrato?.categoria ?? 'EMPLEADO',
    cargo: contrato?.cargo ?? trabajador.cargo ?? '',
    fecha_inicio: contrato?.fecha_inicio ?? trabajador.fecha_ingreso ?? hoy(),
    fecha_fin: contrato?.fecha_fin ?? '',
    sueldo: '',
    observacion: contrato?.observacion ?? '',
  })
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')
  const opciones = {
    exito: editando ? 'Contrato corregido.' : 'Contrato registrado.',
    alExito: (datos) => {
      if (datos.avisos?.length) onAviso(datos.avisos)
      onCerrar()
    },
  }
  const crear = useCrearContrato(trabajador.id, opciones)
  const editar = useEditarContrato(contrato?.id, opciones)
  const mutacion = editando ? editar : crear
  const poner = (campo, valor) => setF((previo) => ({ ...previo, [campo]: valor }))
  const lista = regimenes.data ?? []

  const enviar = (evento) => {
    evento.preventDefault()
    if (mutacion.isPending) return
    const e = {}
    if (!f.regimen) e.regimen = 'Elija el régimen laboral.'
    if (!f.cargo.trim()) e.cargo = 'Indique el cargo.'
    if (!f.fecha_inicio) e.fecha_inicio = 'Indique cuándo empieza.'
    if (f.tipo_contrato === 'PLAZO_FIJO' && !f.fecha_fin) e.fecha_fin = 'Un contrato a plazo fijo necesita su fecha de fin.'
    if (f.fecha_fin && f.fecha_inicio && f.fecha_fin < f.fecha_inicio) e.fecha_fin = 'No puede ser anterior al inicio.'
    if (!editando && (!decimalValido(f.sueldo, 9_999_999.99) || Number(f.sueldo) <= 0)) e.sueldo = 'Un sueldo mensual en soles, mayor que cero.'
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return
    const comun = {
      regimen: Number(f.regimen),
      tipo_contrato: f.tipo_contrato,
      categoria: f.categoria,
      cargo: f.cargo.trim(),
      fecha_fin: f.fecha_fin || null,
      observacion: f.observacion.trim(),
    }
    const alError = { onError: (error) => errorDelServidor(error, setErrores, setGeneral) }
    if (editando) editar.mutate(comun, alError)
    else crear.mutate({ ...comun, fecha_inicio: f.fecha_inicio, sueldo: f.sueldo }, alError)
  }

  return (
    <Modal titulo={editando ? 'Corregir contrato' : 'Nuevo contrato'} subtitulo={trabajador.nombre_completo} onCerrar={onCerrar} ancho={720}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={mutacion.isPending} className="rh-opciones">
          <div className="rh-fila-campos">
            <Campo etiqueta="Régimen laboral" tipo="select" requerido error={errores.regimen}>
              {(p) => (
                <select {...p} value={f.regimen} onChange={(e) => poner('regimen', e.target.value)}>
                  <option value="">Elegir régimen</option>
                  {lista.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.nombre}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Tipo de contrato" tipo="select" requerido error={errores.tipo_contrato}>
              {(p) => (
                <select {...p} value={f.tipo_contrato} onChange={(e) => poner('tipo_contrato', e.target.value)}>
                  {TIPOS_CONTRATO.map(([valor, texto]) => (
                    <option key={valor} value={valor}>
                      {texto}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Categoría" tipo="select" error={errores.categoria}>
              {(p) => (
                <select {...p} value={f.categoria} onChange={(e) => poner('categoria', e.target.value)}>
                  {CATEGORIAS.map(([valor, texto]) => (
                    <option key={valor} value={valor}>
                      {texto}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
          </div>
          <Campo etiqueta="Cargo" requerido error={errores.cargo}>
            {(p) => <input {...p} maxLength={100} placeholder="Ej. Vendedora de mostrador" value={f.cargo} onChange={(e) => poner('cargo', e.target.value)} />}
          </Campo>
          <div className="rh-fila-campos">
            <Campo etiqueta="Inicio" requerido error={errores.fecha_inicio} ayuda={editando ? 'El inicio no se corrige aquí.' : undefined}>
              {(p) => <input {...p} type="date" disabled={editando} value={f.fecha_inicio} onChange={(e) => poner('fecha_inicio', e.target.value)} />}
            </Campo>
            <Campo etiqueta="Fin del contrato" requerido={f.tipo_contrato === 'PLAZO_FIJO'} error={errores.fecha_fin} ayuda="Déjalo vacío si no vence.">
              {(p) => <input {...p} type="date" value={f.fecha_fin} onChange={(e) => poner('fecha_fin', e.target.value)} />}
            </Campo>
            {!editando && (
              <Campo etiqueta="Sueldo mensual (S/)" requerido error={errores.sueldo}>
                {(p) => <input {...p} inputMode="decimal" autoComplete="off" value={f.sueldo} onChange={(e) => poner('sueldo', decimal(e.target.value))} />}
              </Campo>
            )}
          </div>
          {!editando && !verSueldos && <p className="celda-suave">El sueldo lo registra quien tiene el permiso de sueldos.</p>}
          <Campo etiqueta="Observación" error={errores.observacion} contador={{ actual: f.observacion.length, max: 250 }}>
            {(p) => <input {...p} maxLength={250} placeholder="Opcional" value={f.observacion} onChange={(e) => poner('observacion', e.target.value)} />}
          </Campo>
        </fieldset>
        <Pie general={general} enviando={mutacion.isPending} textoEnviar={editando ? 'Guardar cambios' : 'Registrar contrato'} textoEnviando="Guardando…" onCerrar={onCerrar} deshabilitar={regimenes.isLoading} />
      </form>
    </Modal>
  )
}

/** Termina el contrato (renuncia, despido, vencimiento…). No se puede deshacer. */
export function FinalizarModal({ contrato, trabajador, onCerrar }) {
  const [fecha, setFecha] = useState(hoy())
  const [motivo, setMotivo] = useState('')
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')
  const accion = useAccionContrato(contrato.id, 'finalizar', { exito: 'Contrato finalizado.', alExito: onCerrar })

  const enviar = (evento) => {
    evento.preventDefault()
    if (accion.isPending) return
    const e = {}
    if (!fecha) e.fecha_cese = 'Indique la fecha del cese.'
    if (!motivo.trim()) e.motivo = 'Indique el motivo del cese.'
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return
    accion.mutate({ fecha_cese: fecha, motivo: motivo.trim() }, { onError: (error) => errorDelServidor(error, setErrores, setGeneral) })
  }

  return (
    <Modal titulo="Finalizar contrato" subtitulo={trabajador.nombre_completo} onCerrar={onCerrar}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={accion.isPending} className="rh-opciones">
          <p className="rh-aviso">Al finalizar, el contrato ya no se corrige ni se le cambia el sueldo. Si el trabajador vuelve, se registra un contrato nuevo.</p>
          <Campo etiqueta="Fecha del cese" requerido error={errores.fecha_cese} ayuda="No puede ser futura.">
            {(p) => <input {...p} type="date" max={hoy()} value={fecha} onChange={(e) => setFecha(e.target.value)} />}
          </Campo>
          <Campo etiqueta="Motivo" requerido error={errores.motivo} contador={{ actual: motivo.length, max: 200 }}>
            {(p) => <input {...p} maxLength={200} placeholder="Ej. Renuncia voluntaria, término del contrato" value={motivo} onChange={(e) => setMotivo(e.target.value)} />}
          </Campo>
        </fieldset>
        <Pie general={general} enviando={accion.isPending} textoEnviar="Finalizar contrato" textoEnviando="Finalizando…" onCerrar={onCerrar} />
      </form>
    </Modal>
  )
}

/** Un sueldo nuevo desde una fecha: el anterior queda en el historial. */
export function SueldoModal({ contrato, trabajador, onCerrar, onAviso }) {
  const [monto, setMonto] = useState('')
  const [desde, setDesde] = useState(hoy())
  const [motivo, setMotivo] = useState('')
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')
  const accion = useAccionContrato(contrato.id, 'sueldos', {
    exito: 'Sueldo registrado.',
    alExito: (datos) => {
      if (datos.avisos?.length) onAviso(datos.avisos)
      onCerrar()
    },
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (accion.isPending) return
    const e = {}
    if (!decimalValido(monto, 9_999_999.99) || Number(monto) <= 0) e.monto = 'Un sueldo mensual en soles, mayor que cero.'
    if (!desde) e.vigente_desde = 'Indique desde cuándo rige.'
    else if (desde < contrato.fecha_inicio) e.vigente_desde = 'No puede regir antes del inicio del contrato.'
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return
    accion.mutate({ monto, vigente_desde: desde, motivo: motivo.trim() }, { onError: (error) => errorDelServidor(error, setErrores, setGeneral) })
  }

  return (
    <Modal titulo="Cambiar sueldo" subtitulo={trabajador.nombre_completo} onCerrar={onCerrar}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={accion.isPending} className="rh-opciones">
          <p className="rh-aviso">Sueldo actual: <strong>{soles(contrato.sueldo_actual)}</strong>. El nuevo rige desde la fecha que elijas; el anterior se conserva en el historial.</p>
          <div className="rh-fila-campos">
            <Campo etiqueta="Nuevo sueldo mensual (S/)" requerido error={errores.monto}>
              {(p) => <input {...p} inputMode="decimal" autoComplete="off" value={monto} onChange={(e) => setMonto(decimal(e.target.value))} />}
            </Campo>
            <Campo etiqueta="Rige desde" requerido error={errores.vigente_desde}>
              {(p) => <input {...p} type="date" min={contrato.fecha_inicio} value={desde} onChange={(e) => setDesde(e.target.value)} />}
            </Campo>
          </div>
          <Campo etiqueta="Motivo" error={errores.motivo} contador={{ actual: motivo.length, max: 100 }}>
            {(p) => <input {...p} maxLength={100} placeholder="Opcional. Ej. Aumento anual" value={motivo} onChange={(e) => setMotivo(e.target.value)} />}
          </Campo>
        </fieldset>
        <Pie general={general} enviando={accion.isPending} textoEnviar="Registrar sueldo" textoEnviando="Guardando…" onCerrar={onCerrar} />
      </form>
    </Modal>
  )
}
