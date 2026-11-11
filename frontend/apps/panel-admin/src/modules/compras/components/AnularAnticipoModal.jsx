import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { dinero } from '../compras'

/** Anula un anticipo con su motivo: el dinero vuelve a la caja. Solo si no se usó ni se devolvió nada. */
export default function AnularAnticipoModal({ anticipo, onCerrar }) {
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')

  const anular = useMutacion({
    mutationFn: (texto) => api.post(`/compras/anticipos/${anticipo.id}/anular/`, { motivo: texto }).then((r) => r.data),
    invalidar: [['compras'], ['caja'], ['movimientos']],
    exito: 'Anticipo anulado. El dinero volvió a la caja.',
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (anular.isPending) return
    if (motivo.trim().length < 3) return setError('Escriba el motivo de la anulación.')
    setError('')
    anular.mutate(motivo.trim(), { onError: (e) => setError(erroresDeCampo(e).motivo || mensajeDeError(e)) })
  }

  return (
    <Modal titulo="Anular anticipo" subtitulo={`${anticipo.codigo} · ${dinero(anticipo.monto, anticipo.moneda)} a ${anticipo.proveedor_nombre}`} onCerrar={onCerrar} ancho={560}>
      <form onSubmit={enviar} noValidate>
        <p>
          No se borra nada: el anticipo queda anulado con su motivo, el dinero vuelve a la caja de donde salió y se cancela su saldo a favor. Solo se puede anular si no se usó en compras ni el proveedor devolvió parte; si ya pasó, deshaz primero esos usos en «Saldos a favor».
        </p>
        <Campo etiqueta="Motivo" requerido error={error} contador={{ actual: motivo.length, max: 250 }}>
          {(p) => <textarea {...p} rows={3} maxLength={250} value={motivo} disabled={anular.isPending} placeholder="Ej. Se adelantó al proveedor equivocado" onChange={(e) => setMotivo(e.target.value)} />}
        </Campo>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={anular.isPending}>
            Cancelar
          </button>
          <button type="submit" className="peligro" disabled={anular.isPending}>
            {anular.isPending ? 'Anulando…' : 'Anular anticipo'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
