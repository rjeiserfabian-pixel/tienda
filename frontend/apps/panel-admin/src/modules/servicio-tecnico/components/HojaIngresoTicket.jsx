import { EmisorTicket } from '../../ventas/components/TicketPartes'
import { fechaCorta } from '../../almacen/inventario'
import { fechaHora } from '../servicio'
import QrOrden from './QrOrden'
import '../../ventas/ventas.css'
import '../servicio-tecnico.css'

/** La hoja de ingreso en ticket de 80 mm: lo esencial del equipo recibido, con su QR y una línea de firma. */
export default function HojaIngresoTicket({ orden: o }) {
  const e = o.equipo_datos
  return (
    <article className="ticket" aria-label={`Hoja de ingreso ${o.codigo}`}>
      <EmisorTicket emisor={o.emisor} titulo="ORDEN DE SERVICIO" numero={o.codigo} />
      <p>
        <b>INGRESO:</b> {fechaHora(o.fecha_ingreso)}
        {o.fecha_promesa && (
          <>
            <br />
            <b>PROMETIDO:</b> {fechaCorta(o.fecha_promesa)}
          </>
        )}
        <br />
        <b>CLIENTE:</b> {o.cliente_nombre}
        <br />
        {o.cliente_documento}
        {o.cliente_telefono ? ` · Tel. ${o.cliente_telefono}` : ''}
      </p>
      <p>
        <b>EQUIPO:</b> {[e.tipo, e.marca, e.modelo].filter(Boolean).join(' ')}
        {e.numero_serie && (
          <>
            <br />
            <b>SERIE:</b> {e.numero_serie}
          </>
        )}
      </p>
      <p>
        <b>FALLA:</b> {o.falla_reportada}
        <br />
        <b>ESTADO FÍSICO:</b> {o.estado_fisico || 'Sin observaciones'}
        <br />
        <b>ACCESORIOS:</b> {o.accesorios.length === 0 ? 'Ninguno' : o.accesorios.map((a) => `${a.cantidad} ${a.nombre}`).join(', ')}
      </p>
      <div className="ticket-centro">
        <QrOrden orden={o} clase="ticket-qr" publico />
        <small className="ticket-linea">{o.codigo}</small>
        <small className="ticket-linea">Escanea para ver el estado de tu equipo</small>
      </div>
      <p className="ticket-firma ticket-firma-ingreso ticket-centro">Firma del cliente</p>
      <footer>
        <small>El taller no se responsabiliza por la información guardada en el equipo. El presupuesto debe aprobarse antes de reparar.</small>
      </footer>
    </article>
  )
}
