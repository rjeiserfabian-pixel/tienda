import { fechaCorta } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import { EmisorTicket, Logo } from '../../ventas/components/TicketPartes'
import '../../ventas/ventas.css'
import '../servicio-tecnico.css'

const AVISO = 'Este recibo no es un comprobante de pago. El servicio se facturará al entregar el equipo y este adelanto se descontará de lo que se cobre.'

/** El recibo interno de un adelanto en A4: cuánto dejó el cliente, por qué orden y cómo se descuenta. */
export function ReciboAdelantoA4({ orden: o, recibo: r }) {
  const e = o.equipo_datos
  return (
    <article className="documento" aria-label={`Recibo de adelanto ${r.codigo}`}>
      <header>
        <div>
          {o.emisor.tiene_logo && <Logo empresa={o.emisor.empresa} />}
          <h1>{o.emisor.nombre}</h1>
          <span>RUC {o.emisor.ruc}</span>
          {o.emisor.direccion && <span>{o.emisor.direccion}</span>}
          {(o.emisor.telefono || o.emisor.correo) && <span>{[o.emisor.telefono, o.emisor.correo].filter(Boolean).join(' · ')}</span>}
        </div>
        <div className="documento-numero">
          <h1>RECIBO DE ADELANTO</h1>
          <strong>N° {r.codigo}</strong>
          <span>Fecha: {fechaCorta(r.fecha)}</span>
        </div>
      </header>
      <div className="ingreso-cuerpo">
        <p>
          <strong>Recibimos de:</strong> {o.cliente_nombre} · {o.cliente_documento}
          <br />
          <strong>La suma de:</strong> {dinero(r.monto)} ({r.medio_nombre}
          {r.referencia ? ` · Operación ${r.referencia}` : ''})
          <br />
          <strong>A cuenta del servicio:</strong> orden {o.codigo} · {[e.tipo, e.marca, e.modelo].filter(Boolean).join(' ')}
        </p>
        <p className="celda-suave">{AVISO}</p>
      </div>
      <footer>
        <div className="ingreso-firmas">
          <span>Firma del cliente</span>
          <span>Recibido por — {o.emisor.nombre}</span>
        </div>
      </footer>
    </article>
  )
}

/** El mismo recibo en ticket de 80 mm. */
export function ReciboAdelantoTicket({ orden: o, recibo: r }) {
  return (
    <article className="ticket" aria-label={`Recibo de adelanto ${r.codigo}`}>
      <EmisorTicket emisor={o.emisor} titulo="RECIBO DE ADELANTO" numero={r.codigo} />
      <p>
        <b>FECHA:</b> {fechaCorta(r.fecha)}
        <br />
        <b>CLIENTE:</b> {o.cliente_nombre}
        <br />
        <b>ORDEN:</b> {o.codigo}
      </p>
      <dl>
        <div className="ticket-total">
          <dt>ADELANTO</dt>
          <dd>{dinero(r.monto)}</dd>
        </div>
      </dl>
      <p>
        <b>PAGO:</b> {r.medio_nombre}
        {r.referencia ? ` · ${r.referencia}` : ''}
      </p>
      <p className="ticket-firma ticket-centro">Firma del cliente</p>
      <footer>
        <small>{AVISO}</small>
      </footer>
    </article>
  )
}
