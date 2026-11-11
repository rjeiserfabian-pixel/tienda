import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaCorta } from '../../almacen/inventario'
import { numeroInterno } from '../compras'

/** Anula una devolución con su motivo: la mercadería vuelve al almacén y se deshace el dinero. */
export default function AnularDevolucionModal({ devolucion, onCerrar }) {
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')

  const anular = useMutacion({
    mutationFn: (texto) => api.post(`/compras/devoluciones/${devolucion.id}/anular/`, { motivo: texto }).then((r) => r.data),
    invalidar: [['compras'], ['caja'], ['movimientos'], ['stock'], ['kardex']],
    exito: 'Devolución anulada. La mercadería volvió al almacén.',
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
    <Modal titulo="Anular devolución" subtitulo={`N° ${numeroInterno(devolucion)} · ${devolucion.comprobante} del ${fechaCorta(devolucion.fecha_emision)}`} onCerrar={onCerrar} ancho={560}>
      <form onSubmit={enviar} noValidate>
        <p>
          No se borra nada: la devolución queda anulada con su motivo, la mercadería vuelve al almacén por el mismo valor con que salió, las cuotas recuperan lo que se les había rebajado y el reembolso sale de la caja donde entró. Si el saldo a favor de esta devolución ya se usó, no se podrá anular hasta deshacer ese uso.
        </p>
        <Campo etiqueta="Motivo" requerido error={error} contador={{ actual: motivo.length, max: 250 }}>
          {(p) => <textarea {...p} rows={3} maxLength={250} value={motivo} disabled={anular.isPending} placeholder="Ej. La nota de crédito se registró por error" onChange={(e) => setMotivo(e.target.value)} />}
        </Campo>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={anular.isPending}>
            Cancelar
          </button>
          <button type="submit" className="peligro" disabled={anular.isPending}>
            {anular.isPending ? 'Anulando…' : 'Anular devolución'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
