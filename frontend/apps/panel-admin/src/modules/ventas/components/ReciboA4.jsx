import { fechaCorta } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import { importeEnLetras, textoDelQr } from '../ventas'
import { Logo, QrEmisor } from './TicketPartes'

const Dato = ({ etiqueta, valor }) => (
  <p>
    <b>{etiqueta}</b>
    <span>: {valor || '—'}</span>
  </p>
)

/** El recibo de un cobro de cuotas en hoja A4: quién cobra, a quién, cuánto, de qué cuotas y lo que queda. */
export default function ReciboA4({ datos: r, onLogoListo = () => {}, onQrListo = () => {} }) {
  const m = r.moneda
  const qr = textoDelQr(r.emisor)
  const pagos = r.pagos.filter((p) => !p.anulado)
  return (
    <article className="documento documento-venta" aria-label={`Recibo ${r.numero_completo}`}>
      <header>
        <div>
          {r.emisor.tiene_logo && <Logo empresa={r.emisor.empresa} onListo={onLogoListo} />}
          <h1>{r.emisor.nombre}</h1>
          {r.emisor.local && <span>Local: {r.emisor.local}</span>}
          {r.emisor.telefono && <span>TELÉFONOS: {r.emisor.telefono}</span>}
          {r.emisor.sitio_web && <span>WEB: {r.emisor.sitio_web}</span>}
          {r.emisor.tienda_web && <span>TIENDA ONLINE: {r.emisor.tienda_web}</span>}
        </div>
        <div className="documento-caja">
          <span>RUC {r.emisor.ruc}</span>
          <strong>RECIBO DE COBRANZA</strong>
          <strong>{r.numero_completo}</strong>
          {r.anulado && <b className="documento-anulado">ANULADO</b>}
        </div>
      </header>

      <section className="documento-cliente">
        <div>
          <Dato etiqueta="SEÑOR(ES)" valor={r.cliente.nombre} />
          <Dato etiqueta="DNI/RUC" valor={r.cliente.documento} />
          <Dato etiqueta="CONCEPTO" valor="PAGO DE CUOTAS" />
        </div>
        <div>
          <Dato etiqueta="FECHA" valor={`${fechaCorta(r.fecha)}${r.hora ? ` ${r.hora}` : ''}`} />
          <Dato etiqueta="MONEDA" valor={m === 'USD' ? 'DÓLARES' : 'SOLES'} />
          <Dato etiqueta="DOCUMENTO" valor={r.comprobante.numero_completo} />
        </div>
      </section>

      <table className="documento-items">
        <thead>
          <tr>
            <th>CUOTA</th>
            <th>VENCE</th>
            <th>ESTADO</th>
            <th>IMPORTE</th>
            <th>SALDO CRÉD.</th>
          </tr>
        </thead>
        <tbody>
          {r.cuotas.map((c) => (
            <tr key={c.numero}>
              <td>{c.numero}</td>
              <td>{fechaCorta(c.fecha_vencimiento)}</td>
              <td>{c.pagada ? 'PAGADA' : 'PAGO PARCIAL'}</td>
              <td>{Number(c.aplicado).toFixed(2)}</td>
              <td>{Number(c.saldo_credito).toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <table className="documento-totales">
        <thead>
          <tr>
            <th>IMPORTE TOTAL</th>
            <th>SALDO DEL CRÉDITO</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <strong>{dinero(r.total, m)}</strong>
            </td>
            <td>{dinero(r.saldo_credito, m)}</td>
          </tr>
        </tbody>
      </table>

      <footer className="documento-pie">
        <div>
          <span>
            <b>IMPORTE EN LETRAS:</b> {importeEnLetras(r.total, m)}
          </span>
          <span>
            <b>FORMA DE PAGO:</b> {pagos.map((p) => p.medio).join(' + ') || '—'}
          </span>
          {pagos
            .filter((p) => p.referencia)
            .map((p) => (
              <span key={`${p.medio}-${p.referencia}`}>
                {p.medio}: Op. {p.referencia}
              </span>
            ))}
          <span>CAJERO(A): {r.cajero || '—'}</span>
        </div>
        <div>
          {qr && <QrEmisor texto={qr} onListo={onQrListo} />}
          <small>Recibo de cobranza. Conserve este documento.</small>
        </div>
      </footer>
    </article>
  )
}
