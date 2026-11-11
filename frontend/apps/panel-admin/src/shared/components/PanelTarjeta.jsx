import { Icono } from './IconosPanel'
import './listados.css'

/**
 * Tarjeta de contenido (formularios y secciones de una pantalla): mismo marco que las tablas,
 * con un pequeño icono rojo, el título y acciones opcionales a la derecha.
 */
export default function PanelTarjeta({ icono, titulo, descripcion, acciones, children, id }) {
  const idTitulo = id ? `${id}-titulo` : undefined
  return (
    <section className="panel-tarjeta" id={id} aria-labelledby={idTitulo}>
      <header>
        {icono && (
          <span className="panel-tarjeta-icono" aria-hidden="true">
            <Icono nombre={icono} tam={22} />
          </span>
        )}
        <div className="panel-tarjeta-titulo">
          <h3 id={idTitulo}>{titulo}</h3>
          {descripcion && <p>{descripcion}</p>}
        </div>
        {acciones && <div className="panel-tarjeta-acciones">{acciones}</div>}
      </header>
      {children}
    </section>
  )
}
