import { cantidad, fechaCorta } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import { importeEnLetras, textoDelQr } from '../ventas'
import { Logo, QrEmisor } from './TicketPartes'

/** Una fila de los datos del cliente y de la venta: «ETIQUETA : valor». */
const Dato = ({ etiqueta, valor }) => (
  <p>
    <b>{etiqueta}</b>
    <span>: {valor || '—'}</span>
  </p>
)

/**
 * El comprobante de una empresa en hoja A4: quién vende, a quién, qué se llevó, los importes con su
 * monto en letras y cómo se pagó. Es la misma información del ticket, en una hoja completa.
 */
export default function ComprobanteA4({ venta, comprobante: c, onLogoListo = () => {}, onQrListo = () => {} }) {
  const m = venta.moneda
  const cobros = c.cobros ?? []
  const alCredito = venta.forma_pago === 'CREDITO'
  const qr = textoDelQr({ local: c.local, ruc: c.empresa_ruc, telefono: c.empresa_telefono })
  const subtotal = Number(c.op_gravada) + Number(c.op_exonerada) + Number(c.op_inafecta)
  const unidades = c.lineas.reduce((suma, l) => suma + Number(l.cantidad), 0)
  return (
    <article className="documento documento-venta" aria-label={`${c.tipo_nombre} ${c.numero_completo}`}>
      <header>
        <div>
          {c.empresa_tiene_logo && <Logo empresa={c.empresa} onListo={onLogoListo} />}
          <h1>{c.empresa_nombre}</h1>
          {c.local && <span>Local: {c.local}</span>}
          {c.empresa_telefono && <span>TELÉFONOS: {c.empresa_telefono}</span>}
          {c.empresa_sitio_web && <span>WEB: {c.empresa_sitio_web}</span>}
          {c.empresa_tienda_web && <span>TIENDA ONLINE: {c.empresa_tienda_web}</span>}
        </div>
        <div className="documento-caja">
          <span>RUC {c.empresa_ruc}</span>
          <strong>{c.tipo_nombre.toUpperCase()}</strong>
          <strong>{c.numero_completo}</strong>
          {c.estado === 'ANULADO' && <b className="documento-anulado">ANULADO</b>}
        </div>
      </header>

      <section className="documento-cliente">
        <div>
          <Dato etiqueta="SEÑOR(ES)" valor={venta.cliente_nombre} />
          <Dato etiqueta="DNI/RUC" valor={venta.cliente_documento} />
          <Dato etiqueta="DIRECCIÓN" valor={venta.cliente_direccion} />
        </div>
        <div>
          <Dato etiqueta="FECHA" valor={`${fechaCorta(c.fecha)}${c.hora ? ` ${c.hora}` : ''}`} />
          <Dato etiqueta="MONEDA" valor={m === 'USD' ? 'DÓLARES' : 'SOLES'} />
          <Dato etiqueta="CONDICIÓN" valor={alCredito ? 'A CRÉDITO' : 'AL CONTADO'} />
        </div>
      </section>

      <table className="documento-items">
        <thead>
          <tr>
            <th>CANT.</th>
            <th>UNID. MED.</th>
            <th>DESCRIPCIÓN</th>
            <th>P. UNITARIO</th>
            <th>IMPORTE</th>
          </tr>
        </thead>
        <tbody>
          {c.lineas.map((l) => (
            <tr key={l.id}>
              <td>{cantidad(l.cantidad)}</td>
              <td>{l.unidad}</td>
              <td>
                {l.codigo ? `${l.codigo} ` : ''}
                {l.descripcion}
                {l.series.length > 0 && <small> · Serie: {l.series.join(', ')}</small>}
              </td>
              <td>{(Number(l.total) / Number(l.cantidad)).toFixed(2)}</td>
              <td>{Number(l.total).toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <table className="documento-totales">
        <thead>
          <tr>
            <th>SUBTOTAL</th>
            <th>EXONERADA</th>
            <th>INAFECTA</th>
            <th>GRAVADA</th>
            <th>IGV</th>
            <th>TOTAL</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>{dinero(subtotal, m)}</td>
            <td>{dinero(c.op_exonerada, m)}</td>
            <td>{dinero(c.op_inafecta, m)}</td>
            <td>{dinero(c.op_gravada, m)}</td>
            <td>{dinero(c.igv, m)}</td>
            <td>
              <strong>{dinero(c.total, m)}</strong>
            </td>
          </tr>
        </tbody>
      </table>

      <footer className="documento-pie">
        <div>
          <span>
            <b>IMPORTE EN LETRAS:</b> {importeEnLetras(c.total, m)}
          </span>
          <span>ITEMS: {c.lineas.length}{unidades !== c.lineas.length ? ` · UNIDADES: ${cantidad(unidades)}` : ''}</span>
          <span>VENDEDOR: {venta.vendedor_nombre || '—'}</span>
          <span>
            <b>CONDICIÓN DE PAGO:</b> {alCredito ? 'A CRÉDITO' : 'AL CONTADO'}
          </span>
          {!alCredito &&
            cobros.map((k) => (
              <span key={k.id}>
                {k.medio_pago_nombre.toUpperCase()}: {dinero(k.monto, m)}
                {k.referencia ? ` · Op. ${k.referencia}` : ''}
                {Number(k.vuelto) > 0 ? ` (recibido ${dinero(k.recibido, m)}, vuelto ${dinero(k.vuelto, m)})` : ''}
              </span>
            ))}
          {alCredito &&
            (c.cuotas ?? []).map((q) => (
              <span key={q.id}>
                CUOTA {q.numero}: {fechaCorta(q.fecha_vencimiento)} · {dinero(q.monto, m)}
              </span>
            ))}
        </div>
        <div>
          {qr && <QrEmisor texto={qr} onListo={onQrListo} />}
          <small>Comprobante interno de venta.</small>
        </div>
      </footer>
    </article>
  )
}
