import { cantidad as formatoCantidad } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import SeriesDevueltas from './SeriesDevueltas'

/**
 * Los productos del comprobante y lo que se devuelve de cada uno. En los motivos totales (anulación,
 * devolución total) todo lo que queda va marcado y no se edita; en «Devolución por ítem» se escribe
 * la cantidad de cada línea y, si el producto lleva series, se eligen las que vuelven.
 */
export default function LineasNota({ lineas, editable, cantidades, series, importes, moneda, disabled, onCantidad, onSeries }) {
  return (
    <div className="marco-tabla">
      <table className="tabla-datos">
        <thead>
          <tr>
            <th>#</th>
            <th>Producto</th>
            <th>Unid. med.</th>
            <th className="num">Vendido</th>
            <th className="num">Ya devuelto</th>
            <th className="num">Devuelve</th>
            <th>Tipo IGV</th>
            <th className="num">Precio sin IGV</th>
            <th className="num">Importe</th>
          </tr>
        </thead>
        <tbody>
          {lineas.map((l, i) => {
            const queda = Number(l.disponible)
            const n = Number(cantidades[l.id] ?? 0)
            return (
              <tr key={l.id}>
                <td>{String(i + 1).padStart(2, '0')}</td>
                <td className="col-texto">
                  {l.descripcion}
                  {l.vuelve_a && <small className="celda-suave"> · si vuelve al stock, va a {l.vuelve_a}</small>}
                  {editable && l.lleva_serie && n > 0 && n !== queda && <SeriesDevueltas linea={l} n={n} elegidas={series[l.id] ?? []} disabled={disabled} onCambio={(v) => onSeries(l.id, v)} />}
                </td>
                <td>{l.unidad}</td>
                <td className="num">{formatoCantidad(l.cantidad)}</td>
                <td className="num">{formatoCantidad(l.devuelto)}</td>
                <td className="num">
                  {editable && queda > 0 ? (
                    <>
                      <input inputMode="decimal" aria-label={`Cantidad a devolver de ${l.descripcion}`} placeholder="0" value={cantidades[l.id] ?? ''} disabled={disabled} onChange={(e) => onCantidad(l.id, e.target.value.replace(',', '.'))} />
                      <small className="celda-suave"> de {formatoCantidad(queda)}</small>
                    </>
                  ) : (
                    formatoCantidad(n)
                  )}
                </td>
                <td>{l.tipo_igv}</td>
                <td className="num">{dinero(l.precio_unitario, moneda)}</td>
                <td className="num">{importes.has(l.id) ? dinero(importes.get(l.id), moneda) : '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
