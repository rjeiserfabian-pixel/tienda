import { Icono } from './IconosPanel'
import './listados.css'

/** Mensaje centrado de "sin resultados": icono, título, ayuda y (opcional) una acción. */
export default function EstadoVacio({ icono = 'buscar', titulo, descripcion, children }) {
  return (
    <div className="vacio-tabla" role="status">
      <span className="vacio-icono" aria-hidden="true">
        <Icono nombre={icono} tam={30} />
      </span>
      <strong>{titulo}</strong>
      {descripcion && <p>{descripcion}</p>}
      {children && <div className="vacio-accion">{children}</div>}
    </div>
  )
}

/**
 * Fila de tabla que ocupa todo el ancho con el mensaje centrado. La tabla (marco y encabezados)
 * se mantiene visible aunque no haya resultados.
 */
export function FilaVacia({ columnas, ...props }) {
  return (
    <tr className="fila-vacia">
      <td colSpan={columnas}>
        <EstadoVacio {...props} />
      </td>
    </tr>
  )
}
