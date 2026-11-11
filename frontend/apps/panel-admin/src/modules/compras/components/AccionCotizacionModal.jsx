import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'

const ACCIONES = {
  anular: {
    titulo: 'Anular cotización',
    texto: 'La cotización queda anulada con su motivo y ya no se podrán registrar respuestas ni crear órdenes con ella.',
    boton: 'Anular cotización',
    exito: 'Cotización anulada.',
    peligro: true,
    obligatorio: true,
    url: (c) => `/compras/cotizaciones/${c.id}/anular/`,
    cuerpo: (_, motivo) => ({ motivo }),
  },
  declinar: {
    titulo: 'El proveedor no cotiza',
    texto: 'Queda fuera de la comparación. Puedes anotar por qué (por ejemplo, «sin stock»). Si luego cotiza, registra su respuesta y vuelve a entrar.',
    boton: 'Marcar «no cotiza»',
    exito: 'Proveedor marcado como «no cotiza».',
    peligro: false,
    obligatorio: false,
    url: (c) => `/compras/cotizaciones/${c.id}/declinar/`,
    cuerpo: (extra, motivo) => ({ respuesta: extra.respuesta, motivo }),
  },
}

/** Anular la cotización (motivo obligatorio) o marcar que un proveedor no cotiza (motivo opcional). */
export default function AccionCotizacionModal({ cotizacion, accion, respuesta, nombreProveedor, onCerrar }) {
  const config = ACCIONES[accion]
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')

  const ejecutar = useMutacion({
    mutationFn: (texto) => api.post(config.url(cotizacion), config.cuerpo({ respuesta }, texto)).then((r) => r.data),
    invalidar: [['compras']],
    exito: config.exito,
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (ejecutar.isPending) return
    if (config.obligatorio && motivo.trim().length < 3) return setError('Escriba el motivo.')
    setError('')
    ejecutar.mutate(motivo.trim(), { onError: (e) => setError(erroresDeCampo(e).motivo || mensajeDeError(e)) })
  }

  return (
    <Modal titulo={config.titulo} subtitulo={`${cotizacion.codigo}${nombreProveedor ? ` · ${nombreProveedor}` : ''}`} onCerrar={onCerrar} ancho={540}>
      <form onSubmit={enviar} noValidate>
        <p>{config.texto}</p>
        <Campo etiqueta="Motivo" requerido={config.obligatorio} error={error} contador={{ actual: motivo.length, max: 250 }}>
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
