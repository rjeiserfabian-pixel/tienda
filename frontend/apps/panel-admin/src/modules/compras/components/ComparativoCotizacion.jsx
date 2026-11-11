import { Link } from 'react-router-dom'
import { cantidad as formatoCantidad, fechaCorta } from '../../almacen/inventario'
import { dinero, FORMAS_PAGO } from '../compras'
import { ESTADOS_RESPUESTA, ORIGENES_RESPUESTA, precioUnitario } from '../cotizaciones'

const condicionDePago = (p) => (p.forma_pago === 'CREDITO' ? `${FORMAS_PAGO.CREDITO} ${p.plazo_dias} d` : p.forma_pago === 'CONTADO' ? FORMAS_PAGO.CONTADO : '—')

/** Una celda de precio: el mejor va resaltado Y con la palabra «Mejor» (no depende solo del color). */
function Oferta({ oferta, moneda, linea }) {
  if (!oferta || oferta.precio_unitario === null) return <span className="celda-suave">—</span>
  return (
    <div className={`cotiz-oferta${oferta.es_mejor ? ' mejor' : ''}`}>
      <strong>{precioUnitario(oferta.precio_unitario, moneda)}</strong>
      {oferta.es_mejor && <span className="cotiz-marca">Mejor precio</span>}
      {oferta.parcial && (
        <span className="cotiz-marca parcial">
          Ofrece {formatoCantidad(oferta.cantidad_ofrecida)} de {formatoCantidad(linea.cantidad)}
        </span>
      )}
      {oferta.observacion && <span className="sub-texto">{oferta.observacion}</span>}
    </div>
  )
}

/**
 * Cuadro de precios lado a lado. Todo lo calcula el servidor (mejor precio, totales, si la oferta
 * está completa): aquí solo se muestra. La cotización es de una sola moneda, así que nunca se mezclan.
 */
export default function ComparativoCotizacion({ cotizacion: c }) {
  const comp = c.comparativo
  const proveedores = comp.proveedores
  const respondidas = proveedores.filter((p) => p.estado === 'RESPONDIDA')
  const moneda = comp.moneda

  if (proveedores.length === 0) return <p className="estado-vacio">Aún no hay proveedores en esta cotización. Agrégalos arriba para empezar a comparar.</p>
  if (respondidas.length === 0) return <p className="estado-vacio">Todavía ningún proveedor respondió. Cuando registres o importes sus precios, aquí aparece la comparación.</p>

  return (
    <>
      <div className="marco-tabla cotiz-comparativo">
        <table className="tabla-datos">
          <caption className="sr-only">Comparativo de precios por producto y proveedor</caption>
          <thead>
            <tr>
              <th scope="col">Producto</th>
              <th scope="col" className="num">
                Pedido
              </th>
              {proveedores.map((p) => (
                <th scope="col" key={p.respuesta} className={p.mejor_total ? 'cotiz-col-mejor' : undefined}>
                  {p.proveedor_nombre}
                  <span className="pildora" data-tono={ESTADOS_RESPUESTA[p.estado]?.tono}>
                    {ESTADOS_RESPUESTA[p.estado]?.texto}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {comp.lineas.map((l) => (
              <tr key={l.linea}>
                <td className="col-texto">
                  {l.producto_nombre}
                  <span className="sub-texto">{l.producto_codigo}</span>
                </td>
                <td className="num">
                  {formatoCantidad(l.cantidad)} {l.unidad}
                </td>
                {proveedores.map((p) => (
                  <td key={p.respuesta} className={p.mejor_total ? 'cotiz-col-mejor' : undefined}>
                    <Oferta oferta={l.ofertas.find((o) => o.respuesta === p.respuesta)} moneda={moneda} linea={l} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row" colSpan={2}>
                Total de lo que cotizó
              </th>
              {proveedores.map((p) => (
                <td key={p.respuesta} className={p.mejor_total ? 'cotiz-col-mejor' : undefined}>
                  {p.total === null ? <span className="celda-suave">—</span> : <strong>{dinero(p.total, moneda)}</strong>}
                  {p.mejor_total && <span className="cotiz-marca">Mejor total</span>}
                  {p.estado === 'RESPONDIDA' && !p.completa && <span className="cotiz-marca parcial">Incompleta: {p.productos_cotizados} de {comp.lineas.length} productos</span>}
                </td>
              ))}
            </tr>
            <tr>
              <th scope="row" colSpan={2}>
                Forma de pago
              </th>
              {proveedores.map((p) => (
                <td key={p.respuesta}>{p.estado === 'RESPONDIDA' ? condicionDePago(p) : '—'}</td>
              ))}
            </tr>
            <tr>
              <th scope="row" colSpan={2}>
                Entrega
              </th>
              {proveedores.map((p) => (
                <td key={p.respuesta}>{p.estado === 'RESPONDIDA' ? (p.plazo_entrega_dias ? `${p.plazo_entrega_dias} días` : 'Sin dato') : '—'}</td>
              ))}
            </tr>
            <tr>
              <th scope="row" colSpan={2}>
                Precios válidos hasta
              </th>
              {proveedores.map((p) => (
                <td key={p.respuesta}>
                  {p.validez_hasta ? fechaCorta(p.validez_hasta) : '—'}
                  {p.vencida && <span className="cotiz-marca vencida">Oferta vencida</span>}
                </td>
              ))}
            </tr>
            <tr>
              <th scope="row" colSpan={2}>
                Cómo llegó
              </th>
              {proveedores.map((p) => (
                <td key={p.respuesta}>
                  {ORIGENES_RESPUESTA[p.origen] ?? '—'}
                  {p.observacion && <span className="sub-texto">{p.observacion}</span>}
                  {p.orden && (
                    <span className="sub-texto">
                      <Link to={`/compras/ordenes/${p.orden}`}>Ver su orden de compra</Link>
                    </span>
                  )}
                </td>
              ))}
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="celda-suave">
        {comp.precios_incluyen_igv ? 'Precios con IGV incluido.' : 'Precios sin IGV.'} El «mejor total» solo se marca entre quienes cotizaron todos los productos por toda la cantidad: comparar totales de ofertas incompletas engaña.
      </p>
    </>
  )
}
