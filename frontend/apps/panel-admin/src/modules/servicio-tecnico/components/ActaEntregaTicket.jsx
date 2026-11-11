import { fechaCorta } from '../../almacen/inventario'
import { EmisorTicket } from '../../ventas/components/TicketPartes'
import { fechaHora } from '../servicio'
import '../../ventas/ventas.css'
import '../servicio-tecnico.css'

/** El acta de entrega en ticket de 80 mm: lo esencial de la entrega, la garantía y una línea de firma. */
export default function ActaEntregaTicket({ orden: o }) {
  const e = o.equipo_datos
  return (
    <article className="ticket" aria-label={`Acta de entrega ${o.codigo}`}>
      <EmisorTicket emisor={o.emisor} titulo="ACTA DE ENTREGA" numero={o.codigo} />
      <p>
        <b>ENTREGA:</b> {fechaHora(o.fecha_entrega)}
        <br />
        <b>CLIENTE:</b> {o.cliente_nombre}
        <br />
        <b>RECOGE:</b> {o.recogio_nombre}
        {o.recogio_es_titular ? ' (titular)' : ` · DNI ${o.recogio_documento}`}
      </p>
      <p>
        <b>EQUIPO:</b> {[e.tipo, e.marca, e.modelo].filter(Boolean).join(' ')}
        {e.numero_serie && (
          <>
            <br />
            <b>SERIE:</b> {e.numero_serie}
          </>
        )}
        <br />
        <b>ACCESORIOS:</b> {o.accesorios.length === 0 ? 'Ninguno' : o.accesorios.map((a) => `${a.cantidad} ${a.nombre}`).join(', ')}
      </p>
      <p>
        <b>GARANTÍA:</b> {o.garantia.dias > 0 ? `${o.garantia.dias} días, hasta el ${fechaCorta(o.garantia.hasta)}` : o.es_garantia ? 'Servicio en garantía' : 'Sin garantía'}
      </p>
      <p className="ticket-firma ticket-centro">Firma de quien recoge</p>
    </article>
  )
}
