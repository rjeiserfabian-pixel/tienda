import { cantidad, fechaCorta } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import { Logo } from './TicketPartes'

/** La nota de crédito en hoja A4: qué se devolvió, de qué comprobante y cómo se le devolvió al cliente. */
export default function NotaCreditoImpresa({ nota: n }) {
  const m = n.moneda
  return (
    <article className="documento" aria-label={`Nota de crédito ${n.numero_completo}`}>
      <header>
        <div>
          {n.emisor.tiene_logo && <Logo empresa={n.emisor.empresa} />}
          <h1>{n.emisor.nombre}</h1>
          <span>RUC {n.emisor.ruc}</span>
          {n.emisor.direccion && <span>{n.emisor.direccion}</span>}
        </div>
        <div className="documento-numero">
          <h1>NOTA DE CRÉDITO</h1>
          <strong>{n.numero_completo}</strong>
          <span>Fecha: {fechaCorta(n.fecha)}</span>
          <span>Sobre: {n.comprobante_numero}</span>
        </div>
      </header>
      <p>
        <strong>Cliente:</strong> {n.cliente_nombre}
        {n.cliente_documento ? ` · ${n.cliente_tipo_documento} ${n.cliente_documento}` : ''}
        <br />
        <strong>Motivo:</strong> {n.motivo_nombre}
        {n.descripcion ? ` · ${n.descripcion}` : ''}
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
          {n.lineas.map((l) => (
            <tr key={l.id}>
              <td>
                {l.descripcion}
                {l.series.length > 0 && (
                  <>
                    <br />
                    <small>Serie: {l.series.join(', ')}</small>
                  </>
                )}
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
        <div className="documento-total">
          <dt>TOTAL</dt>
          <dd>{dinero(n.total, m)}</dd>
        </div>
      </dl>
      <footer>
        {Number(n.a_cuotas) > 0 && <div>Descontado de lo que el cliente debía: {dinero(n.a_cuotas, m)}.</div>}
        {n.reembolsos.map((r) => (
          <div key={r.id}>
            Devuelto en {r.medio_pago_nombre}: {dinero(r.monto, m)}
            {r.referencia ? ` (Op. ${r.referencia})` : ''}
          </div>
        ))}
        <div>Emitida por {n.emitida_por_nombre || '—'}. Documento interno.</div>
      </footer>
    </article>
  )
}
