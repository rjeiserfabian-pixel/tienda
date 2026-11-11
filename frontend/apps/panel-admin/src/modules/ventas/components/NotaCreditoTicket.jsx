import { cantidad, fechaCorta } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import { EmisorTicket } from './TicketPartes'

/** La nota de crédito en ticket de 80 mm: sobre qué comprobante, qué se devolvió y cómo se le devolvió al cliente. */
export default function NotaCreditoTicket({ nota: n }) {
  const m = n.moneda
  return (
    <article className="ticket" aria-label={`Nota de crédito ${n.numero_completo}`}>
      <EmisorTicket emisor={n.emisor} titulo="NOTA DE CRÉDITO" numero={n.numero_completo} />
      <p>
        <b>CLIENTE</b>
        <br />
        {n.cliente_documento ? `${n.cliente_tipo_documento} ${n.cliente_documento}` : 'Sin documento'}
        <br />
        {n.cliente_nombre}
      </p>
      <p>
        <b>FECHA EMISIÓN:</b> {fechaCorta(n.fecha)}
        <br />
        <b>SOBRE:</b> {n.comprobante_numero}
        <br />
        <b>MOTIVO:</b> {n.motivo_nombre}
        {n.descripcion && (
          <>
            <br />
            <b>SUSTENTO:</b> {n.descripcion}
          </>
        )}
      </p>
      <table>
        <thead>
          <tr>
            <th>Cant.</th>
            <th>Descripción</th>
            <th>Total</th>
          </tr>
        </thead>
        <tbody>
          {n.lineas.map((l) => (
            <tr key={l.id}>
              <td>
                {cantidad(l.cantidad)} {l.unidad}
              </td>
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
        {Number(n.op_gravada) > 0 && (
          <div>
            <dt>Op. gravada</dt>
            <dd>{dinero(n.op_gravada, m)}</dd>
          </div>
        )}
        {Number(n.op_exonerada) > 0 && (
          <div>
            <dt>Op. exonerada</dt>
            <dd>{dinero(n.op_exonerada, m)}</dd>
          </div>
        )}
        {Number(n.op_inafecta) > 0 && (
          <div>
            <dt>Op. inafecta</dt>
            <dd>{dinero(n.op_inafecta, m)}</dd>
          </div>
        )}
        <div>
          <dt>IGV</dt>
          <dd>{dinero(n.igv, m)}</dd>
        </div>
        <div className="ticket-total">
          <dt>TOTAL</dt>
          <dd>{dinero(n.total, m)}</dd>
        </div>
      </dl>
      <p>
        {Number(n.a_cuotas) > 0 && (
          <>
            Descontado de la deuda: {dinero(n.a_cuotas, m)}
            <br />
          </>
        )}
        {n.reembolsos.map((r) => (
          <span key={r.id}>
            Devuelto en {r.medio_pago_nombre}: {dinero(r.monto, m)}
            {r.referencia ? ` (Op. ${r.referencia})` : ''}
            <br />
          </span>
        ))}
      </p>
      <footer>
        <small>Emitida por {n.emitida_por_nombre || '—'}. Documento interno.</small>
      </footer>
    </article>
  )
}
