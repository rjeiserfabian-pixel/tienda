import { useState } from 'react'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { parsearSeriesDeVenta } from '../ventas'

/** Series o IMEI de lo que se vende: una por línea, tantas como unidades. */
export default function SeriesVentaModal({ linea, onGuardar, onCerrar }) {
  const [texto, setTexto] = useState(linea.series.join('\n'))
  const necesarias = Number(linea.cantidad) || 0
  const series = parsearSeriesDeVenta(texto)
  const mensaje = series.length === necesarias ? '' : `Llevas ${series.length} de ${necesarias}.`

  const guardar = (evento) => {
    evento.preventDefault()
    if (series.length !== necesarias) return
    onGuardar(series)
    onCerrar()
  }

  return (
    <Modal titulo="Series o IMEI" subtitulo={linea.ficha.nombre} onCerrar={onCerrar} ancho={520}>
      <form onSubmit={guardar} noValidate>
        <Campo etiqueta={`Series (${necesarias})`} requerido error={mensaje} ayuda="Escanéalas o escríbelas: una por línea. Deben estar en el stock de la empresa que vende.">
          {(p) => <textarea {...p} rows={Math.min(Math.max(necesarias, 3), 10)} autoFocus value={texto} onChange={(e) => setTexto(e.target.value)} />}
        </Campo>
        <div className="acciones">
          <button type="button" onClick={onCerrar}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={series.length !== necesarias}>
            Guardar series
          </button>
        </div>
      </form>
    </Modal>
  )
}
