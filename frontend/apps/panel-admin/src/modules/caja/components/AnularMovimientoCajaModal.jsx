import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaCorta } from '../../almacen/inventario'
import { dinero, TIPOS } from '../caja'

/** Anula un ingreso o egreso hecho a mano: deja de contar en el saldo y queda su motivo. */
export default function AnularMovimientoCajaModal({ movimiento, onCerrar }) {
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')

  const anular = useMutacion({
    mutationFn: (texto) => api.post(`/caja/movimientos/${movimiento.id}/anular/`, { motivo: texto }).then((r) => r.data),
    invalidar: [['caja']],
    exito: 'Movimiento anulado. Ya no cuenta en el saldo.',
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
    <Modal titulo="Anular movimiento" subtitulo={`${TIPOS[movimiento.tipo]} N° ${String(movimiento.numero).padStart(6, '0')} · ${dinero(movimiento.monto, movimiento.moneda)} del ${fechaCorta(movimiento.fecha)}`} onCerrar={onCerrar} ancho={520}>
      <form onSubmit={enviar} noValidate>
        <p>No se borra nada: el movimiento queda como anulado con su motivo y deja de contar en el saldo de {movimiento.cuenta_nombre}.</p>
        <Campo etiqueta="Motivo" requerido error={error} contador={{ actual: motivo.length, max: 250 }}>
          {(p) => <textarea {...p} rows={3} maxLength={250} value={motivo} disabled={anular.isPending} placeholder="Ej. Se registró en la caja equivocada" onChange={(e) => setMotivo(e.target.value)} />}
        </Campo>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={anular.isPending}>
            Cancelar
          </button>
          <button type="submit" className="peligro" disabled={anular.isPending}>
            {anular.isPending ? 'Anulando…' : 'Anular movimiento'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
