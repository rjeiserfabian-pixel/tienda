import { Icono } from '../../../shared/components/IconosPanel'
import { cantidad as formatoCantidad } from '../../almacen/inventario'

/**
 * Los productos que viajan: cuánto de cada uno (por defecto todo lo que falta enviar) y su peso en kilos.
 * Un producto se quita de la guía vaciando su cantidad (o con la «x»); no puede pasar de lo pendiente.
 */
export default function LineasGuia({ lineas, cantidades, pesos, disabled, onCantidad, onPeso, onQuitar }) {
  return (
    <div className="marco-tabla">
      <table className="tabla-datos">
        <thead>
          <tr>
            <th>#</th>
            <th>Producto</th>
            <th>Unid. med.</th>
            <th className="num">Vendido</th>
            <th className="num">Ya enviado</th>
            <th className="num">Cantidad</th>
            <th className="num">Peso (kg)</th>
            <th className="centrado">
              <span className="sr-only">Quitar</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {lineas.map((l, i) => {
            const queda = Number(l.pendiente)
            return (
              <tr key={l.id}>
                <td>{String(i + 1).padStart(2, '0')}</td>
                <td className="col-texto">
                  {l.codigo && <strong>{l.codigo} </strong>}
                  {l.descripcion}
                </td>
                <td>{l.unidad}</td>
                <td className="num">{formatoCantidad(l.cantidad)}</td>
                <td className="num">{formatoCantidad(l.enviado)}</td>
                <td className="num">
                  <input inputMode="decimal" aria-label={`Cantidad a enviar de ${l.descripcion}`} placeholder="0" value={cantidades[l.id] ?? ''} disabled={disabled || queda <= 0} onChange={(e) => onCantidad(l.id, e.target.value)} />
                  <small className="celda-suave"> de {formatoCantidad(queda)}</small>
                </td>
                <td className="num">
                  <input inputMode="decimal" aria-label={`Peso en kilos de ${l.descripcion}`} placeholder="0.000" value={pesos[l.id] ?? ''} disabled={disabled || queda <= 0} onChange={(e) => onPeso(l.id, e.target.value)} />
                </td>
                <td className="centrado">
                  <button type="button" className="accion-icono peligro-suave" aria-label={`Quitar ${l.descripcion} de la guía`} title="Quitar" disabled={disabled || queda <= 0 || !cantidades[l.id]} onClick={() => onQuitar(l.id)}>
                    <Icono nombre="cerrar" tam={16} />
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
