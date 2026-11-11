import { cantidad } from '../../almacen/inventario'
import { dinero } from '../compras'

const TOTALES = [
  ['op_gravada', 'Operación gravada'],
  ['op_ivap', 'Operación IVAP'],
  ['op_exonerada', 'Operación exonerada'],
  ['op_inafecta', 'Operación inafecta'],
  ['igv', 'IGV'],
  ['ivap', 'IVAP'],
  ['ajuste_redondeo', 'Redondeo'],
]

/** Lo que se compró (producto, cantidad, precio, IGV, importe y costo en inventario) y los totales del comprobante. */
export default function DetalleLineas({ compra }) {
  const moneda = compra.moneda
  return (
    <>
      <div className="marco-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th>Producto</th>
              <th className="num">Cantidad</th>
              <th className="num">Precio unit.</th>
              <th>IGV</th>
              <th className="num">Importe</th>
              <th className="num">Costo en inventario</th>
            </tr>
          </thead>
          <tbody>
            {compra.lineas.map((l) => (
              <tr key={l.id}>
                <td>
                  <strong>{l.producto_nombre}</strong>
                  <span className="sub-texto">
                    {l.producto_codigo}
                    {l.lote ? ` · Lote ${l.lote}` : ''}
                  </span>
                </td>
                <td className="num">
                  {cantidad(l.cantidad)} {l.unidad}
                  {Number(l.factor) !== 1 && <span className="sub-texto">= {cantidad(l.cantidad_base)} en unidad base</span>}
                </td>
                <td className="num">{dinero(l.precio_unitario, moneda)}</td>
                <td className="celda-suave">{l.afectacion_codigo === '10' ? `Gravado ${Number(l.tasa)}%` : `Afectación ${l.afectacion_codigo}`}</td>
                <td className="num">{dinero(l.total, moneda)}</td>
                <td className="num">
                  {dinero(l.costo_soles)}
                  {Number(l.flete_asignado) > 0 && <span className="sub-texto">incluye flete {dinero(l.flete_asignado)}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="compra-totales compra-totales-ficha">
        {TOTALES.filter(([clave]) => Number(compra[clave]) !== 0).map(([clave, texto]) => (
          <div key={clave}>
            <dt>{texto}</dt>
            <dd>{dinero(compra[clave], moneda)}</dd>
          </div>
        ))}
        <div className="compra-total">
          <dt>Total</dt>
          <dd>{dinero(compra.total, moneda)}</dd>
        </div>
      </dl>
    </>
  )
}
