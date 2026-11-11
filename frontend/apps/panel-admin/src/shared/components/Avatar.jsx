import './listados.css'

/** Color estable por nombre: la misma persona siempre tiene el mismo tono. */
function tonoDe(texto) {
  let hash = 0
  for (const c of texto) hash = (hash * 31 + c.charCodeAt(0)) % 360
  return hash
}

function inicialesDe(nombre) {
  return (
    nombre
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((p) => p[0].toUpperCase())
      .join('') || '?'
  )
}

/** Círculo con las iniciales (aún no se guardan fotos de usuarios). */
export default function Avatar({ nombre, tam = 40 }) {
  const tono = tonoDe(nombre)
  return (
    <span
      className="avatar-tabla"
      aria-hidden="true"
      style={{
        width: tam,
        height: tam,
        background: `linear-gradient(135deg, hsl(${tono} 55% 42%), hsl(${(tono + 40) % 360} 55% 24%))`,
      }}
    >
      {inicialesDe(nombre)}
    </span>
  )
}
