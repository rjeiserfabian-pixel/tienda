import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaCorta } from '../../almacen/inventario'
import { dinero } from '../caja'

/** Anula una transferencia con todos sus movimientos: el dinero vuelve a la cuenta de la que salió. */
export default function AnularTransferenciaModal({ transferencia, onCerrar }) {
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')

  const anular = useMutacion({
    mutationFn: (texto) => api.post(`/caja/transferencias/${transferencia.id}/anular/`, { motivo: texto }).then((r) => r.data),
    invalidar: [['caja']],
    exito: 'Transferencia anulada. El dinero volvió a su cuenta.',
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
    <Modal titulo={`Anular ${transferencia.clase_nombre.toLowerCase()}`} subtitulo={`N° ${String(transferencia.numero).padStart(6, '0')} · ${dinero(transferencia.monto_origen, transferencia.origen_moneda)} del ${fechaCorta(transferencia.fecha)}`} onCerrar={onCerrar} ancho={520}>
      <form onSubmit={enviar} noValidate>
        <p>
          No se borra nada: queda anulada con su motivo y se anulan sus movimientos (la salida de {transferencia.origen_nombre}, la entrada a {transferencia.destino_nombre} y su comisión o ITF, si los hubo).
        </p>
        <Campo etiqueta="Motivo" requerido error={error} contador={{ actual: motivo.length, max: 250 }}>
          {(p) => <textarea {...p} rows={3} maxLength={250} value={motivo} disabled={anular.isPending} placeholder="Ej. Se depositó en la cuenta equivocada" onChange={(e) => setMotivo(e.target.value)} />}
        </Campo>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={anular.isPending}>
            Cancelar
          </button>
          <button type="submit" className="peligro" disabled={anular.isPending}>
            {anular.isPending ? 'Anulando…' : 'Anular'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
