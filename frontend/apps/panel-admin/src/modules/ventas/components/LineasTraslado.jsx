import { cantidad as formatoCantidad } from '../../almacen/inventario'

/**
 * Los productos de un traspaso: viajan todos y completos (la cantidad no se cambia, ya salió del almacén), con
 * sus series o IMEI si los tienen. Solo se escribe el peso en kilos de cada uno.
 */
export default function LineasTraslado({ lineas, pesos, disabled, onPeso }) {
  return (
    <div className="marco-tabla">
      <table className="tabla-datos">
        <thead>
          <tr>
            <th>#</th>
            <th>Producto</th>
            <th>Unid. med.</th>
            <th className="num">Cantidad</th>
            <th className="num">Peso (kg)</th>
          </tr>
        </thead>
        <tbody>
          {lineas.map((l, i) => (
            <tr key={l.id}>
              <td>{String(i + 1).padStart(2, '0')}</td>
              <td className="col-texto">
                {l.codigo && <strong>{l.codigo} </strong>}
                {l.descripcion}
                {l.series.length > 0 && <span className="sub-texto">Series: {l.series.join(', ')}</span>}
              </td>
              <td>{l.unidad}</td>
              <td className="num">{formatoCantidad(l.cantidad)}</td>
              <td className="num">
                <input inputMode="decimal" aria-label={`Peso en kilos de ${l.descripcion}`} placeholder="0.000" value={pesos[l.id] ?? ''} disabled={disabled} onChange={(e) => onPeso(l.id, e.target.value)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
