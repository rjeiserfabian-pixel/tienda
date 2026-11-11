import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaCorta } from '../../almacen/inventario'
import { dinero } from '../compras'

/** Anula un pago hecho a una compra a crédito: cada cuota recupera lo que había recibido de él. */
export default function AnularPagoModal({ compra, pago, onCerrar }) {
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')

  const anular = useMutacion({
    mutationFn: (texto) => api.post(`/compras/${compra.id}/pagos/${pago.id}/anular/`, { motivo: texto }).then((r) => r.data),
    invalidar: [['compras'], ['caja']],
    exito: 'Pago anulado. La deuda volvió a las cuotas.',
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (anular.isPending) return
    if (!motivo.trim()) return setError('Escriba el motivo de la anulación.')
    setError('')
    anular.mutate(motivo.trim(), { onError: (e) => setError(erroresDeCampo(e).motivo || mensajeDeError(e)) })
  }

  return (
    <Modal titulo="Anular pago" subtitulo={`${dinero(pago.monto, compra.moneda)} del ${fechaCorta(pago.fecha)} · ${compra.comprobante}`} onCerrar={onCerrar} ancho={520}>
      <form onSubmit={enviar} noValidate>
        <p>No se borra nada: el pago queda como anulado con su motivo y la deuda vuelve a las cuotas que había cubierto. Si lo hiciste por error de monto o de caja, anúlalo y registra el correcto.</p>
        <Campo etiqueta="Motivo" requerido error={error} contador={{ actual: motivo.length, max: 250 }}>
          {(p) => <textarea {...p} rows={3} maxLength={250} value={motivo} disabled={anular.isPending} placeholder="Ej. Se pagó desde la caja equivocada" onChange={(e) => setMotivo(e.target.value)} />}
        </Campo>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={anular.isPending}>Cancelar</button>
          <button type="submit" className="peligro" disabled={anular.isPending}>
            {anular.isPending ? 'Anulando…' : 'Anular pago'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
