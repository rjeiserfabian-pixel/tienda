import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'

const ACCIONES = {
  rechazar: {
    titulo: 'Rechazar orden',
    texto: 'La orden vuelve a borrador con tu motivo para que quien la creó la corrija.',
    boton: 'Rechazar orden',
    exito: 'Orden rechazada: volvió a borrador.',
    peligro: false,
  },
  anular: {
    titulo: 'Anular orden',
    texto: 'La orden queda anulada con su motivo y no se podrá recibir mercadería contra ella. Solo se puede si todavía no llegó nada.',
    boton: 'Anular orden',
    exito: 'Orden anulada.',
    peligro: true,
  },
  cerrar: {
    titulo: 'Cerrar orden',
    texto: 'Se da por terminada aunque falte mercadería: el proveedor no entregará el resto. Lo ya recibido se queda como está.',
    boton: 'Cerrar orden',
    exito: 'Orden cerrada.',
    peligro: false,
  },
}

/** Rechazar, anular o cerrar una orden: las tres piden un motivo. */
export default function AccionOrdenModal({ orden, accion, onCerrar }) {
  const config = ACCIONES[accion]
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')

  const ejecutar = useMutacion({
    mutationFn: (texto) => api.post(`/compras/ordenes/${orden.id}/${accion}/`, { motivo: texto }).then((r) => r.data),
    invalidar: [['compras']],
    exito: config.exito,
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (ejecutar.isPending) return
    if (motivo.trim().length < 3) return setError('Escriba el motivo.')
    setError('')
    ejecutar.mutate(motivo.trim(), { onError: (e) => setError(erroresDeCampo(e).motivo || mensajeDeError(e)) })
  }

  return (
    <Modal titulo={config.titulo} subtitulo={`${orden.codigo} · ${orden.proveedor_nombre}`} onCerrar={onCerrar} ancho={540}>
      <form onSubmit={enviar} noValidate>
        <p>{config.texto}</p>
        <Campo etiqueta="Motivo" requerido error={error} contador={{ actual: motivo.length, max: 250 }}>
          {(p) => <textarea {...p} rows={3} maxLength={250} value={motivo} disabled={ejecutar.isPending} onChange={(e) => setMotivo(e.target.value)} />}
        </Campo>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={ejecutar.isPending}>
            Cancelar
          </button>
          <button type="submit" className={config.peligro ? 'peligro' : 'primario'} disabled={ejecutar.isPending}>
            {ejecutar.isPending ? 'Un momento…' : config.boton}
          </button>
        </div>
      </form>
    </Modal>
  )
}
