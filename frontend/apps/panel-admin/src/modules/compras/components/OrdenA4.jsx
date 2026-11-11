import { fechaCorta } from '../../almacen/inventario'
import { dinero, FORMAS_PAGO } from '../compras'
import { ESTADOS_ORDEN } from '../ordenes'

const Dato = ({ etiqueta, valor }) => (
  <p>
    <b>{etiqueta}</b>
    <span>: {valor || '—'}</span>
  </p>
)

const cantidad = (valor) => Number(valor).toLocaleString('es-PE', { maximumFractionDigits: 3 })

/** La orden de compra en hoja A4, lista para enviarla al proveedor. */
export default function OrdenA4({ datos: o }) {
  const e = o.emisor
  const p = o.proveedor_datos
  const moneda = o.moneda
  const borrador = o.estado === 'BORRADOR' || o.estado === 'PENDIENTE'
  const totales = [
    ['OP. GRAVADA', o.op_gravada],
    ['OP. IVAP', o.op_ivap],
    ['OP. EXONERADA', o.op_exonerada],
    ['OP. INAFECTA', o.op_inafecta],
    ['IGV', o.igv],
    ['IVAP', o.ivap],
  ].filter(([texto, valor]) => Number(valor) !== 0 || texto === 'IGV')

  return (
    <article className="documento documento-venta" aria-label={`Orden de compra ${o.codigo}`}>
      <header>
        <div>
          <h1>{e.nombre_comercial || e.nombre}</h1>
          {e.nombre_comercial && <span>{e.nombre}</span>}
          {e.direccion && <span>{e.direccion}</span>}
          {e.telefono && <span>Tel. {e.telefono}</span>}
        </div>
        <div className="documento-caja">
          <span>RUC {e.ruc}</span>
          <strong>ORDEN DE COMPRA</strong>
          <strong>{o.codigo}</strong>
          {borrador && <b className="documento-anulado">{ESTADOS_ORDEN[o.estado].texto.toUpperCase()}</b>}
          {o.estado === 'ANULADA' && <b className="documento-anulado">ANULADA</b>}
        </div>
      </header>

      <section className="documento-cliente">
        <div>
          <Dato etiqueta="PROVEEDOR" valor={o.proveedor_nombre} />
          <Dato etiqueta={p.tipo_documento || 'DOCUMENTO'} valor={p.numero_documento} />
          <Dato etiqueta="DIRECCIÓN" valor={[p.direccion, p.ciudad].filter(Boolean).join(' · ')} />
          <Dato etiqueta="CONTACTO" valor={[p.contacto, p.telefono].filter(Boolean).join(' · ')} />
        </div>
        <div>
          <Dato etiqueta="FECHA" valor={fechaCorta(o.fecha_emision)} />
          <Dato etiqueta="ENTREGA ESPERADA" valor={o.fecha_entrega ? fechaCorta(o.fecha_entrega) : ''} />
          <Dato etiqueta="ENTREGAR EN" valor={o.almacen_nombre} />
          <Dato etiqueta="PAGO" valor={o.forma_pago === 'CREDITO' ? `${FORMAS_PAGO.CREDITO} a ${o.plazo_dias} días` : FORMAS_PAGO.CONTADO} />
          <Dato etiqueta="MONEDA" valor={moneda === 'USD' ? `Dólares (T.C. ${o.tipo_cambio})` : 'Soles'} />
        </div>
      </section>

      <table className="documento-items">
        <thead>
          <tr>
            <th>ITEM</th>
            <th>CANT.</th>
            <th>DESCRIPCIÓN</th>
            <th>U.M.</th>
            <th>P. UNIT.</th>
            <th>IMPORTE</th>
          </tr>
        </thead>
        <tbody>
          {o.lineas.map((l) => (
            <tr key={l.id}>
              <td>{l.orden_linea}</td>
              <td>{cantidad(l.cantidad)}</td>
              <td>
                {l.producto_nombre}
                <small style={{ display: 'block' }}>{l.producto_codigo}</small>
              </td>
              <td>{l.unidad}</td>
              <td>{Number(l.precio_unitario).toLocaleString('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}</td>
              <td>{dinero(l.total, moneda)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <table className="documento-totales">
        <tbody>
          {totales.map(([texto, valor]) => (
            <tr key={texto}>
              <th>{texto}</th>
              <td>{dinero(valor, moneda)}</td>
            </tr>
          ))}
          <tr>
            <th>
              <strong>TOTAL</strong>
            </th>
            <td>
              <strong>{dinero(o.total, moneda)}</strong>
            </td>
          </tr>
        </tbody>
      </table>
      {o.precios_incluyen_igv && <p style={{ fontSize: 11 }}>Los precios unitarios incluyen IGV.</p>}
      {o.observacion && <p style={{ fontSize: 11 }}>Observación: {o.observacion}</p>}

      <footer className="documento-pie">
        <div>
          <span>Autorizado por: ______________________________</span>
        </div>
        <div>
          <small>Orden de compra. Indique este número {o.codigo} en su guía y su comprobante.</small>
        </div>
      </footer>
    </article>
  )
}
