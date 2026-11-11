import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'

/** Reabre la última sesión cerrada de una caja. El sobrante o faltante del cierre se deshace. */
export default function ReabrirSesionModal({ sesion, onCerrar }) {
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')

  const reabrir = useMutacion({
    mutationFn: (texto) => api.post(`/caja/sesiones/${sesion.id}/reabrir/`, { motivo: texto }).then((r) => r.data),
    invalidar: [['caja']],
    exito: 'Sesión reabierta.',
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (reabrir.isPending) return
    if (!motivo.trim()) return setError('Escriba el motivo de la reapertura.')
    setError('')
    reabrir.mutate(motivo.trim(), { onError: (e) => setError(erroresDeCampo(e).motivo || mensajeDeError(e)) })
  }

  return (
    <Modal titulo="Reabrir la sesión" subtitulo={`${sesion.cuenta_nombre} · sesión ${String(sesion.numero).padStart(6, '0')}`} onCerrar={onCerrar} ancho={520}>
      <form onSubmit={enviar} noValidate>
        <p>Si el cierre tenía un sobrante o faltante, se anula: la caja vuelve a mostrar lo que el sistema esperaba. Después hay que contar y cerrar otra vez.</p>
        <Campo etiqueta="Motivo" requerido error={error} contador={{ actual: motivo.length, max: 250 }}>
          {(p) => <textarea {...p} rows={3} maxLength={250} value={motivo} disabled={reabrir.isPending} placeholder="Ej. Faltó registrar un cobro de la tarde" onChange={(e) => setMotivo(e.target.value)} />}
        </Campo>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={reabrir.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={reabrir.isPending}>
            {reabrir.isPending ? 'Reabriendo…' : 'Reabrir'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
