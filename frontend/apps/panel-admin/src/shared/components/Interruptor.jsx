import './modal.css'

/** Interruptor accesible (role="switch"): `activo`, texto principal y una descripción breve. */
export default function Interruptor({ activo, onCambio, texto, descripcion, disabled }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={activo}
      className="interruptor"
      disabled={disabled}
      onClick={() => onCambio(!activo)}
    >
      <span className="interruptor-pista" aria-hidden="true" />
      <span>
        <strong>{texto}</strong>
        {descripcion && <small>{descripcion}</small>}
      </span>
    </button>
  )
}
