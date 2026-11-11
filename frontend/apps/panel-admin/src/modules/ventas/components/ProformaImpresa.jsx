import { cantidad, fechaCorta } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import { Logo } from './TicketPartes'

/** La proforma en hoja A4: quién cotiza, para quién, qué incluye, cuánto vale y hasta cuándo. */
export default function ProformaImpresa({ proforma: p }) {
  const m = p.moneda
  const varias = p.por_empresa.length > 1
  return (
    <article className="documento" aria-label={`Proforma ${p.numero}`}>
      <header>
        <div>
          {p.emisor.tiene_logo && <Logo empresa={p.emisor.empresa} />}
          <h1>{p.emisor.nombre}</h1>
          <span>RUC {p.emisor.ruc}</span>
          {p.emisor.direccion && <span>{p.emisor.direccion}</span>}
          {(p.emisor.telefono || p.emisor.correo) && <span>{[p.emisor.telefono, p.emisor.correo].filter(Boolean).join(' · ')}</span>}
        </div>
        <div className="documento-numero">
          <h1>PROFORMA</h1>
          <strong>N° {p.numero_completo}</strong>
          <span>Fecha: {fechaCorta(p.fecha)}</span>
          <span>Válida hasta: {fechaCorta(p.valida_hasta)}</span>
        </div>
      </header>
      <p>
        <strong>Cliente:</strong> {p.cliente_nombre}
        {p.cliente_documento ? ` · ${p.cliente_documento}` : ''}
        {p.cliente_contacto ? ` · ${p.cliente_contacto}` : ''}
        {p.cliente_direccion && (
          <>
            <br />
            <strong>Dirección:</strong> {p.cliente_direccion}
          </>
        )}
        {p.atencion && (
          <>
            <br />
            <strong>Con atención a:</strong> {p.atencion}
          </>
        )}
        <br />
        <strong>Atendió:</strong> {p.vendedor_nombre}
        {p.lista_nombre ? ` · Lista ${p.lista_nombre}` : ''}
        {p.forma_pago === 'CREDITO' ? ' · A crédito' : ' · Al contado'}
        {m === 'USD' ? ` · Dólares (T.C. ${p.tipo_cambio})` : ''}
      </p>
      <table>
        <thead>
          <tr>
            <th>Descripción</th>
            <th>Cant.</th>
            <th>P. unit. sin IGV</th>
            <th>IGV</th>
            <th>Importe</th>
          </tr>
        </thead>
        <tbody>
          {p.lineas.map((l) => (
            <tr key={l.id}>
              <td>
                {l.descripcion}
                <br />
                <small>
                  {l.codigo}
                  {varias ? ` · ${l.empresa_nombre}` : ''}
                </small>
              </td>
              <td>
                {cantidad(l.cantidad)} {l.unidad}
              </td>
              <td>{dinero(l.precio_unitario, m)}</td>
              <td>{dinero(l.igv, m)}</td>
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
        <div className="documento-total">
          <dt>TOTAL</dt>
          <dd>{dinero(p.total, m)}</dd>
        </div>
      </dl>
      {(p.fecha_entrega || p.lugar_entrega) && (
        <p>
          <strong>Entrega:</strong> {[p.fecha_entrega && fechaCorta(p.fecha_entrega), p.lugar_entrega].filter(Boolean).join(' · ')}
        </p>
      )}
      {p.condiciones && (
        <p>
          <strong>Condiciones:</strong> {p.condiciones}
        </p>
      )}
      <footer>
        <span>Esta proforma no reserva stock ni es un comprobante de pago; los precios pueden variar después de {fechaCorta(p.valida_hasta)}.</span>
        {varias && <span className="proforma-pie-estado"> Se emitirá un comprobante por cada empresa.</span>}
      </footer>
    </article>
  )
}
