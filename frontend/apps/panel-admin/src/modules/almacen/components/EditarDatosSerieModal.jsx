import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'

const MAXIMO = 120

/** Corrige los otros datos de una serie. El número de serie no se cambia ni se toca el stock. */
export default function EditarDatosSerieModal({ serie, onCerrar }) {
  const { empresaActivaId } = useEmpresas()
  const [datos, setDatos] = useState(serie.otros_datos ?? '')
  const [error, setError] = useState('')
  const sinCambios = datos.trim().replace(/\s+/g, ' ') === (serie.otros_datos ?? '')

  const guardar = useMutacion({
    mutationFn: (cuerpo) => api.patch(`/inventario/series/${serie.id}/`, cuerpo, { params: { empresa: empresaActivaId } }).then((r) => r.data),
    invalidar: [['series']],
    exito: 'Datos de la serie actualizados.',
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending || sinCambios) return
    setError('')
    guardar.mutate({ otros_datos: datos }, { onError: (e) => setError(erroresDeCampo(e).otros_datos || mensajeDeError(e)) })
  }

  return (
    <Modal titulo={`Datos de la serie ${serie.numero}`} subtitulo={serie.producto_nombre} onCerrar={onCerrar} ancho={480}>
      <form onSubmit={enviar} noValidate>
        <Campo etiqueta="Otros datos" error={error} ayuda="Opcional. Por ejemplo el color, la garantía o el estado de esta unidad. El número de serie no se cambia.">
          {(p) => <input {...p} autoFocus maxLength={MAXIMO} placeholder="Ej. Negro, 128 GB" value={datos} disabled={guardar.isPending} onChange={(e) => setDatos(e.target.value)} />}
        </Campo>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={guardar.isPending}>Cancelar</button>
          <button type="submit" className="primario" disabled={guardar.isPending || sinCambios}>{guardar.isPending ? 'Guardando…' : 'Guardar'}</button>
        </div>
      </form>
    </Modal>
  )
}
