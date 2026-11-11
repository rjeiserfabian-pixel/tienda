import { useState } from 'react'
import { codigoDeError, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { usePrepararPlanilla } from '../hooks/usePlanilla'
import { MESES } from '../rrhh'
import '../rrhh.css'

const hoy = new Date()

/** Prepara la planilla de un mes: la calcula con la asistencia, los adelantos y los valores legales. */
export default function PlanillaNuevaModal({ onCerrar, onCreada }) {
  const { empresaActivaId } = useEmpresas()
  // Lo habitual es preparar el mes que acaba de terminar, o el actual si ya es fin de mes.
  const inicial = hoy.getDate() >= 25 ? { anio: hoy.getFullYear(), mes: hoy.getMonth() + 1 } : { anio: hoy.getMonth() === 0 ? hoy.getFullYear() - 1 : hoy.getFullYear(), mes: hoy.getMonth() === 0 ? 12 : hoy.getMonth() }
  const [f, setF] = useState({ anio: String(inicial.anio), mes: String(inicial.mes) })
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')
  const cuerpo = { empresa: empresaActivaId, anio: Number(f.anio) || null, mes: Number(f.mes) || null }
  const llave = useClaveIdempotente(cuerpo)
  const preparar = usePrepararPlanilla({ exito: 'Planilla preparada. Revísela antes de cerrarla.', alExito: (p) => (onCreada ? onCreada(p) : onCerrar()) })

  const enviar = (evento) => {
    evento.preventDefault()
    if (preparar.isPending) return
    const e = {}
    if (!/^\d{4}$/.test(f.anio) || Number(f.anio) < 2000 || Number(f.anio) > 2100) e.anio = 'Indique un año válido.'
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return
    preparar.mutate(
      { datos: cuerpo, llave },
      {
        onError: (error) => {
          const delServidor = erroresDeCampo(error)
          setErrores(delServidor)
          setGeneral(Object.keys(delServidor).length > 0 && codigoDeError(error) === 'validacion' ? 'Revise los datos marcados.' : mensajeDeError(error))
        },
      },
    )
  }

  return (
    <Modal titulo="Preparar planilla" subtitulo="Se calcula con la asistencia, los adelantos y los valores legales del mes." onCerrar={onCerrar} ancho={480}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={preparar.isPending} className="rh-opciones">
          <div className="rh-fila-campos">
            <Campo etiqueta="Mes" tipo="select" requerido error={errores.mes}>
              {(p) => (
                <select {...p} value={f.mes} onChange={(e) => setF({ ...f, mes: e.target.value })}>
                  {MESES.map((nombre, i) => (
                    <option key={nombre} value={i + 1}>
                      {nombre}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Año" requerido error={errores.anio}>
              {(p) => <input {...p} inputMode="numeric" maxLength={4} value={f.anio} onChange={(e) => setF({ ...f, anio: e.target.value.replace(/\D/g, '') })} />}
            </Campo>
          </div>
          <p className="celda-suave">Si falta marcar días de asistencia o cargar algún valor legal, la planilla se prepara igual y te avisa qué corregir antes de cerrarla.</p>
        </fieldset>
        {general && (
          <p role="alert" className="campo-error">
            {general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={preparar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={preparar.isPending}>
            {preparar.isPending ? 'Calculando…' : 'Preparar planilla'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
