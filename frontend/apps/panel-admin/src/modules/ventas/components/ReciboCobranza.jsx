import { fechaCorta } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import { textoDelQr } from '../ventas'
import { Logo, QrEmisor } from './TicketPartes'

/** El recibo de 80 mm de un cobro de cuotas: quién cobra, a quién, cuánto, de qué cuotas y lo que queda. */
export default function ReciboTicket({ datos: r, onLogoListo = () => {}, onQrListo = () => {} }) {
  const m = r.moneda
  const qr = textoDelQr(r.emisor)
  return (
    <article className="ticket ticket-recibo" aria-label={`Recibo ${r.numero_completo}`}>
      <header>
        {r.emisor.tiene_logo && <Logo empresa={r.emisor.empresa} onListo={onLogoListo} />}
        <strong>{r.emisor.nombre}</strong>
        {r.emisor.local && <span>Local: {r.emisor.local}</span>}
        {r.emisor.telefono && <span>TELÉFONOS: {r.emisor.telefono}</span>}
        {r.emisor.sitio_web && <span>WEB: {r.emisor.sitio_web}</span>}
        {r.emisor.tienda_web && <span>TIENDA ONLINE: {r.emisor.tienda_web}</span>}
        <span>RUC: {r.emisor.ruc}</span>
        <b>RECIBO {r.numero_completo}</b>
        {r.anulado && <b className="ticket-anulado">ANULADO</b>}
      </header>
      <p>
        <b>CLIENTE</b>
        <br />
        {r.cliente.documento ? `${r.cliente.tipo_documento} ${r.cliente.documento}` : 'Sin documento'}
        <br />
        {r.cliente.nombre}
      </p>
      <p>
        <b>FECHA EMISIÓN:</b> {fechaCorta(r.fecha)}
        <br />
        <b>HORA:</b> {r.hora}
        <br />
        <b>MONEDA:</b> {m}
        <br />
        <b>FORMA DE PAGO:</b> {r.pagos.filter((p) => !p.anulado).map((p) => p.medio).join(' + ')}
        <br />
        <b>CAJERO(A):</b> {r.cajero || '—'}
        <br />
        <b>CONCEPTO:</b> PAGO DE CUOTAS
      </p>
      <table>
        <thead>
          <tr>
            <th>CUOTA</th>
            <th>VENCE</th>
            <th>IMPORTE</th>
            <th>SALDO CRÉD.</th>
          </tr>
        </thead>
        <tbody>
          {r.cuotas.map((c) => (
            <tr key={c.numero}>
              <td>{c.numero}</td>
              <td>{fechaCorta(c.fecha_vencimiento)}</td>
              <td>{Number(c.aplicado).toFixed(2)}</td>
              <td>{Number(c.saldo_credito).toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="ticket-centro">
        DOCUMENTO: {r.comprobante.numero_completo}
        <br />
        <b>PAGO DE CUOTAS</b>
        {r.cuotas.map((c) => (
          <span key={c.numero}>
            <br />
            CUOTA {c.numero}: {c.pagada ? 'PAGADA' : 'PAGO PARCIAL'}
            <br />
            F. VENCIMIENTO: {fechaCorta(c.fecha_vencimiento)}
          </span>
        ))}
      </p>
      {r.pagos.some((p) => p.referencia) && (
        <p>
          {r.pagos
            .filter((p) => p.referencia)
            .map((p) => (
              <span key={`${p.medio}-${p.referencia}`}>
                {p.medio}: Op. {p.referencia}
                <br />
              </span>
            ))}
        </p>
      )}
      <dl>
        <div className="ticket-total">
          <dt>Importe Total</dt>
          <dd>{dinero(r.total, m)}</dd>
        </div>
        <div>
          <dt>Saldo del crédito</dt>
          <dd>{dinero(r.saldo_credito, m)}</dd>
        </div>
      </dl>
      {qr && (
        <div className="ticket-centro">
          <QrEmisor texto={qr} onListo={onQrListo} />
        </div>
      )}
      <footer>
        <small>Recibo de cobranza. Conserve este documento.</small>
      </footer>
    </article>
  )
}
