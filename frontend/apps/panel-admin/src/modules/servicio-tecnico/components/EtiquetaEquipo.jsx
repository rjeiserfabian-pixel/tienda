import { fechaHora } from '../servicio'
import QrOrden from './QrOrden'
import '../servicio-tecnico.css'

/** La etiqueta que se pega en el equipo: el código de la orden y un QR que abre su ficha en el panel. */
export default function EtiquetaEquipo({ orden: o }) {
  const e = o.equipo_datos
  return (
    <article className="etiqueta" aria-label={`Etiqueta ${o.codigo}`}>
      <QrOrden orden={o} clase="" />
      <div>
        <strong>{o.codigo}</strong>
        <span>{o.cliente_nombre}</span>
        <span>{[e.tipo, e.marca, e.modelo].filter(Boolean).join(' ')}</span>
        {e.numero_serie && <span>Serie {e.numero_serie}</span>}
        <span>{fechaHora(o.fecha_ingreso).slice(0, 10)}</span>
      </div>
    </article>
  )
}
