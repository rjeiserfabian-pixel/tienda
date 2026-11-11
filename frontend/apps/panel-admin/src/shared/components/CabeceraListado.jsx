import { Icono } from './IconosPanel'
import './listados.css'

/**
 * Tarjeta de cabecera de un listado: icono, título, descripción y a la derecha las acciones
 * (buscador, filtros, exportar, botón de alta…), que se pasan como hijos.
 */
export default function CabeceraListado({ icono, avatar, titulo, descripcion, children }) {
  return (
    <header className="cabecera-listado">
      {avatar ?? (
        <span className="cabecera-icono" aria-hidden="true">
          <Icono nombre={icono} tam={30} />
        </span>
      )}
      <div className="cabecera-texto">
        <h2>{titulo}</h2>
        {descripcion && <p>{descripcion}</p>}
      </div>
      <div className="cabecera-acciones">{children}</div>
    </header>
  )
}

/** Buscador con lupa para la cabecera. El valor se retrasa fuera (useDebounce) antes de consultar. */
export function Buscador({ valor, onCambio, etiqueta, placeholder }) {
  return (
    <label className="buscador">
      <span className="sr-only">{etiqueta}</span>
      <Icono nombre="buscar" tam={19} />
      <input type="search" value={valor} onChange={(e) => onCambio(e.target.value)} placeholder={placeholder} />
    </label>
  )
}
