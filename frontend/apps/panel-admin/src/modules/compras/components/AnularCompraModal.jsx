import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaCorta } from '../../almacen/inventario'
import { numeroInterno } from '../compras'

/** Anula una compra con su motivo: la mercadería sale del inventario y sus pagos quedan marcados como anulados. */
export default function AnularCompraModal({ compra, onCerrar }) {
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')

  const anular = useMutacion({
    mutationFn: (texto) => api.post(`/compras/${compra.id}/anular/`, { motivo: texto }).then((r) => r.data),
    invalidar: [['compras'], ['caja'], ['movimientos'], ['stock'], ['kardex']],
    exito: 'Compra anulada. La mercadería salió del inventario.',
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
    <Modal titulo="Anular compra" subtitulo={`N° ${numeroInterno(compra)} · ${compra.comprobante} del ${fechaCorta(compra.fecha_emision)}`} onCerrar={onCerrar} ancho={520}>
      <form onSubmit={enviar} noValidate>
        <p>
          No se borra nada: la compra queda como anulada con su motivo y el inventario se corrige con un movimiento inverso. Si la mercadería ya se vendió o si ya se pagó alguna cuota, no se podrá anular.
        </p>
        <Campo etiqueta="Motivo" requerido error={error} contador={{ actual: motivo.length, max: 250 }}>
          {(p) => <textarea {...p} rows={3} maxLength={250} value={motivo} disabled={anular.isPending} placeholder="Ej. Factura registrada por error" onChange={(e) => setMotivo(e.target.value)} />}
        </Campo>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={anular.isPending}>
            Cancelar
          </button>
          <button type="submit" className="peligro" disabled={anular.isPending}>
            {anular.isPending ? 'Anulando…' : 'Anular compra'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
