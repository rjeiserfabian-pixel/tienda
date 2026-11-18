import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'

/** Abre el reclamo de una garantía: qué falla tiene el producto y, si no lleva serie, cuántas unidades. */
export default function ReclamarModal({ garantia, onCerrar, onCreado }) {
  const [descripcion, setDescripcion] = useState('')
  const [cantidad, setCantidad] = useState('1')
  const [error, setError] = useState('')
  const sinSerie = !garantia.numero_serie
  const maximo = Number(garantia.cantidad)

  const abrir = useMutacion({
    mutationFn: (cuerpo) => api.post('/garantias/reclamos/', cuerpo).then((r) => r.data),
    invalidar: [['garantias']],
    exito: (reclamo) => `Reclamo ${reclamo.numero_completo} abierto.`,
    alExito: (reclamo) => onCreado?.(reclamo),
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (abrir.isPending) return
    setError('')
    if (descripcion.trim().length < 3) return setError('Cuéntanos qué falla tiene el producto.')
    const cuerpo = { garantia: garantia.id, descripcion: descripcion.trim() }
    if (sinSerie) cuerpo.cantidad = cantidad
    abrir.mutate(cuerpo, { onError: (e) => setError(Object.values(erroresDeCampo(e))[0] ?? mensajeDeError(e)) })
  }

  return (
    <Modal titulo="Reclamar garantía" subtitulo={`${garantia.producto_nombre}${garantia.numero_serie ? ` · ${garantia.numero_serie}` : ''}`} onCerrar={onCerrar} ancho={520}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={abrir.isPending}>
          <Campo etiqueta="¿Qué falla tiene?" requerido contador={{ actual: descripcion.length, max: 1000 }}>
            {(props) => <textarea {...props} rows={4} maxLength={1000} autoFocus value={descripcion} onChange={(e) => setDescripcion(e.target.value)} />}
          </Campo>
          {sinSerie && maximo > 1 && (
            <Campo etiqueta="Unidades con falla" requerido ayuda={`Se vendieron ${maximo}.`}>
              {(props) => <input {...props} type="number" min="1" max={maximo} step="1" value={cantidad} onChange={(e) => setCantidad(e.target.value)} />}
            </Campo>
          )}
        </fieldset>
        {error && (
          <p role="alert" className="campo-error">
            {error}
          </p>
        )}
        <div className="acciones">
          <button type="button" onClick={onCerrar}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={abrir.isPending}>
            {abrir.isPending ? 'Abriendo…' : 'Abrir reclamo'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
