import { cantidad, fechaCorta } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import { EmisorTicket } from './TicketPartes'

/** La proforma en ticket de 80 mm: para quién es, qué incluye, cuánto vale y hasta cuándo. */
export default function ProformaTicket({ proforma: p }) {
  const m = p.moneda
  const varias = p.por_empresa.length > 1
  return (
    <article className="ticket" aria-label={`Proforma ${p.numero_completo}`}>
      <EmisorTicket emisor={p.emisor} titulo="PROFORMA N°" numero={p.numero_completo} />
      <p>
        <b>CLIENTE</b>
        <br />
        {p.cliente_documento ? `${p.cliente_documento} · ` : ''}
        {p.cliente_nombre}
        {p.cliente_contacto && (
          <>
            <br />
            {p.cliente_contacto}
          </>
        )}
        {p.atencion && (
          <>
            <br />
            Con atención a: {p.atencion}
          </>
        )}
      </p>
      <p>
        <b>FECHA:</b> {fechaCorta(p.fecha)}
        <br />
        <b>VÁLIDA HASTA:</b> {fechaCorta(p.valida_hasta)}
        <br />
        <b>ATENDIÓ:</b> {p.vendedor_nombre}
        <br />
        <b>PAGO:</b> {p.forma_pago === 'CREDITO' ? 'A CRÉDITO' : 'AL CONTADO'}
        {m === 'USD' ? ` · DÓLARES (T.C. ${p.tipo_cambio})` : ''}
      </p>
      <table>
        <thead>
          <tr>
            <th>Cant.</th>
            <th>Descripción</th>
            <th>Importe</th>
          </tr>
        </thead>
        <tbody>
          {p.lineas.map((l) => (
            <tr key={l.id}>
              <td>
                {cantidad(l.cantidad)} {l.unidad}
              </td>
              <td>
                {l.descripcion}
                {varias && <small> · {l.empresa_nombre}</small>}
              </td>
              <td>{dinero(l.total, m)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <dl>
        {varias &&
          p.por_empresa.map((e) => (
            <div key={e.empresa}>
              <dt>{e.nombre}</dt>
              <dd>{dinero(e.total, m)}</dd>
            </div>
          ))}
        <div className="ticket-total">
          <dt>TOTAL</dt>
          <dd>{dinero(p.total, m)}</dd>
        </div>
      </dl>
      {(p.fecha_entrega || p.lugar_entrega) && (
        <p>
          <b>ENTREGA:</b> {[p.fecha_entrega && fechaCorta(p.fecha_entrega), p.lugar_entrega].filter(Boolean).join(' · ')}
        </p>
      )}
      {p.condiciones && (
        <p>
          <b>CONDICIONES:</b> {p.condiciones}
        </p>
      )}
      <footer>
        <small>Esta proforma no reserva stock ni es un comprobante de pago; los precios pueden variar después de {fechaCorta(p.valida_hasta)}.</small>
      </footer>
    </article>
  )
}
