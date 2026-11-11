import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { ESTADOS_ORDEN } from '../servicio'

const AYUDAS = {
  APROBADO: { etiqueta: '¿Cómo respondió el cliente?', placeholder: 'Ej. Aprobó el presupuesto por WhatsApp.' },
  NO_APROBADO: { etiqueta: 'Motivo', placeholder: 'Ej. El cliente decidió no repararlo.' },
  SIN_SOLUCION: { etiqueta: 'Por qué no tiene solución', placeholder: 'Ej. La placa no tiene reparación.' },
  ABANDONADO: { etiqueta: 'Motivo', placeholder: 'Ej. No respondió a los avisos en el plazo informado.' },
  PENDIENTE_REPUESTO: { etiqueta: 'Qué repuesto se espera', placeholder: 'Ej. Memoria RAM DDR4 de 8 GB.' },
}

/** Pasa la orden a otro estado. Si el paso lo pide, hay que explicar el motivo (queda en el historial). */
export default function CambioEstadoModal({ orden, destino, onCerrar }) {
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')
  const estado = ESTADOS_ORDEN[destino.estado]
  const ayuda = AYUDAS[destino.estado] ?? { etiqueta: 'Motivo', placeholder: 'Explica por qué se hace este cambio.' }

  const cambiar = useMutacion({
    mutationFn: (cuerpo) => api.post(`/servicio-tecnico/ordenes/${orden.id}/estado/`, cuerpo).then((r) => r.data),
    invalidar: [['servicio']],
    exito: `La orden ${orden.codigo} pasó a «${estado?.texto ?? destino.nombre}».`,
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (cambiar.isPending) return
    if (destino.pide_motivo && motivo.trim().length < 5) return setError('Explica el motivo con unas palabras.')
    setError('')
    cambiar.mutate({ estado: destino.estado, motivo: motivo.trim() }, { onError: (e) => setError(erroresDeCampo(e).motivo || mensajeDeError(e)) })
  }

  return (
    <Modal titulo={`Pasar a «${estado?.texto ?? destino.nombre}»`} subtitulo={`Orden ${orden.codigo} · ${orden.cliente_nombre}`} onCerrar={onCerrar} ancho={540}>
      <form onSubmit={enviar} noValidate>
        <Campo etiqueta={ayuda.etiqueta} requerido={destino.pide_motivo} error={error} contador={{ actual: motivo.length, max: 500 }}>
          {(p) => <textarea {...p} rows={3} maxLength={500} placeholder={ayuda.placeholder} value={motivo} disabled={cambiar.isPending} onChange={(e) => setMotivo(e.target.value)} />}
        </Campo>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={cambiar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={cambiar.isPending}>
            {cambiar.isPending ? 'Guardando…' : 'Confirmar'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
