import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaCorta, ORIGENES } from '../inventario'

/** Anula un movimiento con su motivo: el sistema crea el extorno que compensa el stock y el costo. */
export default function AnularMovimientoModal({ movimiento, onCerrar }) {
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')

  const anular = useMutacion({
    mutationFn: (texto) => api.post(`/inventario/movimientos/${movimiento.id}/anular/`, { motivo: texto }).then((r) => r.data),
    invalidar: [['movimientos'], ['stock'], ['kardex']],
    exito: 'Movimiento anulado. Quedó registrado su extorno.',
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (anular.isPending) return
    if (!motivo.trim()) return setError('Escriba el motivo de la anulación.')
    setError('')
    anular.mutate(motivo.trim(), {
      onError: (e) => setError(erroresDeCampo(e).motivo || mensajeDeError(e)),
    })
  }

  return (
    <Modal titulo="Anular movimiento" subtitulo={`N° ${String(movimiento.numero).padStart(6, '0')} · ${ORIGENES[movimiento.origen]} del ${fechaCorta(movimiento.fecha)}`} onCerrar={onCerrar} ancho={520}>
      <form onSubmit={enviar} noValidate>
        <p>
          No se borra nada: el sistema registra un movimiento inverso con la fecha de hoy y deja constancia del motivo. Si la mercadería ya salió del almacén, no se podrá anular.
        </p>
        <Campo etiqueta="Motivo" requerido error={error} contador={{ actual: motivo.length, max: 250 }}>
          {(p) => <textarea {...p} rows={3} maxLength={250} value={motivo} disabled={anular.isPending} placeholder="Ej. Factura registrada por error" onChange={(e) => setMotivo(e.target.value)} />}
        </Campo>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={anular.isPending}>Cancelar</button>
          <button type="submit" className="peligro" disabled={anular.isPending}>
            {anular.isPending ? 'Anulando…' : 'Anular movimiento'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
