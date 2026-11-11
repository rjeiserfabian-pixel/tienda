import { cantidad, fechaCorta } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import { textoDelQr } from '../ventas'
import { Logo, QrEmisor } from './TicketPartes'

/** Lo que dice el ticket del comprobante: a quién, cuándo, qué se llevó y con qué se pagó. */
export default function Ticket({ venta, comprobante: c, onLogoListo = () => {}, onQrListo = () => {} }) {
  const m = venta.moneda
  const emisor = { local: c.local, ruc: c.empresa_ruc, telefono: c.empresa_telefono }
  const qr = textoDelQr(emisor)
  const cobros = c.cobros ?? []
  const cajas = [...new Set(cobros.map((k) => k.cuenta_nombre).filter(Boolean))]
  const alCredito = venta.forma_pago === 'CREDITO'
  return (
    <article className="ticket" aria-label={`Ticket ${c.numero_completo}`}>
      <header>
        {c.empresa_tiene_logo && <Logo empresa={c.empresa} onListo={onLogoListo} />}
        <strong>{c.empresa_nombre}</strong>
        {c.local && <span>Local: {c.local}</span>}
        {c.empresa_telefono && <span>TELÉFONOS: {c.empresa_telefono}</span>}
        {c.empresa_sitio_web && <span>WEB: {c.empresa_sitio_web}</span>}
        {c.empresa_tienda_web && <span>TIENDA ONLINE: {c.empresa_tienda_web}</span>}
        <span>RUC: {c.empresa_ruc}</span>
        <b>
          {c.tipo_nombre.toUpperCase()} {c.numero_completo}
        </b>
        {c.estado === 'ANULADO' && <b className="ticket-anulado">ANULADO</b>}
      </header>
      <p>
        <b>CLIENTE</b>
        <br />
        {venta.cliente_documento ? `${venta.cliente_tipo_documento} ${venta.cliente_documento}` : 'Sin documento'}
        <br />
        {venta.cliente_nombre}
      </p>
      <p>
        <b>FECHA EMISIÓN:</b> {fechaCorta(c.fecha)}
        {c.hora ? ` · ${c.hora}` : ''}
        <br />
        <b>VENDEDOR:</b> {venta.vendedor_nombre || '—'}
        <br />
        <b>CONDICIÓN DE PAGO:</b> {alCredito ? 'A CRÉDITO' : 'AL CONTADO'}
        {!alCredito && cobros.length > 0 && (
          <>
            <br />
            <b>FORMA DE PAGO:</b> {[...new Set(cobros.map((k) => k.medio_pago_nombre))].join(' + ')}
            <br />
            <b>DETALLE:</b>
            {cobros.map((k) => (
              <span key={k.id}>
                <br />
                {k.medio_pago_nombre}: {dinero(k.monto, m)}
                {k.referencia ? ` · Op. ${k.referencia}` : ''}
                {Number(k.vuelto) > 0 ? ` (recibido ${dinero(k.recibido, m)}, vuelto ${dinero(k.vuelto, m)})` : ''}
              </span>
            ))}
          </>
        )}
        {cajas.length > 0 && (
          <>
            <br />
            <b>CAJA:</b> {cajas.join(', ')}
          </>
        )}
      </p>
      <table>
        <thead>
          <tr>
            <th>Cant.</th>
            <th>U.M.</th>
            <th>Descripción</th>
            <th>Total</th>
          </tr>
        </thead>
        <tbody>
          {c.lineas.map((l) => (
            <tr key={l.id}>
              <td>{cantidad(l.cantidad)}</td>
              <td>{l.unidad}</td>
              <td>
                {l.descripcion}
                {l.series.length > 0 && <small> · Serie: {l.series.join(', ')}</small>}
              </td>
              <td>{dinero(l.total, m)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <dl>
        {Number(c.op_gravada) > 0 && (
          <div>
            <dt>Op. gravada</dt>
            <dd>{dinero(c.op_gravada, m)}</dd>
          </div>
        )}
        {Number(c.op_exonerada) > 0 && (
          <div>
            <dt>Op. exonerada</dt>
            <dd>{dinero(c.op_exonerada, m)}</dd>
          </div>
        )}
        {Number(c.op_inafecta) > 0 && (
          <div>
            <dt>Op. inafecta</dt>
            <dd>{dinero(c.op_inafecta, m)}</dd>
          </div>
        )}
        <div>
          <dt>IGV</dt>
          <dd>{dinero(c.igv, m)}</dd>
        </div>
        <div className="ticket-total">
          <dt>TOTAL</dt>
          <dd>{dinero(c.total, m)}</dd>
        </div>
      </dl>
      {alCredito && c.cuotas?.length > 0 && (
        <p>
          <b>CUOTAS</b>
          {c.cuotas.map((q) => (
            <span key={q.id}>
              <br />
              {q.numero}. {fechaCorta(q.fecha_vencimiento)} · {dinero(q.monto, m)}
            </span>
          ))}
        </p>
      )}
      {qr && (
        <div className="ticket-centro">
          <QrEmisor texto={qr} onListo={onQrListo} />
        </div>
      )}
      <footer>
        <span>¡Gracias por su compra!</span>
        <small>Comprobante interno de venta.</small>
      </footer>
    </article>
  )
}
