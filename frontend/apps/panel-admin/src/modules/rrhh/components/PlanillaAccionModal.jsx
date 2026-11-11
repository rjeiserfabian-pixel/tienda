import { useState } from 'react'
import { mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useAccionPlanilla, useDescartarPlanilla } from '../hooks/usePlanilla'
import { mesAnio, soles } from '../rrhh'
import '../rrhh.css'

const TEXTOS = {
  cerrar: {
    titulo: 'Cerrar la planilla',
    boton: 'Cerrar planilla',
    exito: 'Planilla cerrada.',
  },
  reabrir: {
    titulo: 'Reabrir la planilla',
    boton: 'Reabrir planilla',
    exito: 'Planilla reabierta: ya se puede corregir.',
  },
  descartar: {
    titulo: 'Descartar la planilla',
    boton: 'Descartar planilla',
    exito: 'Planilla descartada.',
  },
}

/** Confirma cerrar, reabrir o descartar una planilla y muestra lo que responda el servidor. */
export default function PlanillaAccionModal({ planilla, tipo, onCerrar, onListo }) {
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')
  const texto = TEXTOS[tipo]
  const accion = useAccionPlanilla(planilla.id, tipo, { exito: texto.exito, alExito: () => onCerrar() })
  const descartar = useDescartarPlanilla(planilla.id, { exito: texto.exito, alExito: () => onListo?.() })
  const enviando = accion.isPending || descartar.isPending
  const mes = mesAnio(planilla.periodo)

  const confirmar = (evento) => {
    evento.preventDefault()
    if (enviando) return
    setError('')
    const alError = { onError: (e) => setError(mensajeDeError(e)) }
    if (tipo === 'descartar') return descartar.mutate(undefined, alError)
    if (tipo === 'reabrir') {
      if (!motivo.trim()) return setError('Indique el motivo de la reapertura.')
      return accion.mutate({ motivo: motivo.trim() }, alError)
    }
    // Se manda el neto que la persona está viendo: si cambió, el servidor no cierra.
    return accion.mutate({ total_neto: planilla.total_neto }, alError)
  }

  return (
    <Modal titulo={`${texto.titulo} de ${mes}`} onCerrar={onCerrar} ancho={520}>
      <form onSubmit={confirmar} noValidate className="rh-opciones">
        {tipo === 'cerrar' && (
          <>
            <p>
              Se fijan los montos de <strong>{planilla.num_trabajadores}</strong> trabajador(es) por un neto de <strong>{soles(planilla.total_neto)}</strong>.
            </p>
            <p className="rh-aviso">Al cerrar: las cuotas de adelantos y préstamos de {mes} se dan por descontadas y ya no se puede cambiar la asistencia ni programar descuentos en ese mes.</p>
          </>
        )}
        {tipo === 'reabrir' && (
          <>
            <p className="rh-aviso">Las cuotas descontadas vuelven a «por descontar» y se libera la asistencia del mes. Quedará registrado quién y por qué.</p>
            <fieldset disabled={enviando} className="rh-opciones">
              <Campo etiqueta="Motivo de la reapertura" requerido error={error} contador={{ actual: motivo.length, max: 250 }}>
                {(p) => <input {...p} maxLength={250} value={motivo} onChange={(e) => setMotivo(e.target.value)} />}
              </Campo>
            </fieldset>
          </>
        )}
        {tipo === 'descartar' && <p>Se elimina la planilla de {mes} junto con los bonos y descuentos que se hayan agregado a mano. Puedes volver a prepararla cuando quieras.</p>}
        {error && tipo !== 'reabrir' && (
          <p role="alert" className="campo-error">
            {error}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={enviando}>
            Cancelar
          </button>
          <button type="submit" className={tipo === 'descartar' ? 'peligro' : 'primario'} disabled={enviando}>
            {enviando ? 'Procesando…' : texto.boton}
          </button>
        </div>
      </form>
    </Modal>
  )
}
