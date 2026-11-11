import { dinero } from '../../compras/compras'

// Colores de la dona: contraste alto sobre fondo oscuro y distinguibles entre sí.
const COLORES = ['#ff5a4a', '#f5a623', '#3ec28f', '#4da3ff', '#b57aff', '#ff7ac6', '#8a8f9c']

const RADIO = 44
const LARGO = 2 * Math.PI * RADIO

/** Un monto por moneda, nunca sumados entre sí. Sin datos muestra cero en soles. */
export function Montos({ filas, campo, tono }) {
  const lista = filas?.length ? filas : [{ moneda: 'PEN', [campo]: '0' }]
  return (
    <span className="montos">
      {lista.map((f) => (
        <span key={f.moneda} className="monto-linea" data-tono={tono}>
          {dinero(f[campo], f.moneda)}
        </span>
      ))}
    </span>
  )
}

/** Mensaje cuando un bloque no se pudo calcular: los demás siguen funcionando. */
export function NoDisponible() {
  return <p className="inicio-pendiente">No se pudo cargar esta información. Intenta de nuevo en un momento.</p>
}

/** Dona con leyenda: las porciones suman 100 % y cada una trae su nombre y porcentaje. */
export function Dona({ filas, moneda }) {
  const total = filas.reduce((suma, f) => suma + Number(f.valor), 0)
  if (!filas.length || total <= 0) {
    return <p className="estado-vacio">Aún no hay ventas este mes.</p>
  }
  let acumulado = 0
  const arcos = filas.map((f, i) => {
    const parte = Number(f.valor) / total
    const arco = { nombre: f.nombre, parte, color: COLORES[i % COLORES.length], inicio: acumulado }
    acumulado += parte
    return arco
  })
  return (
    <div className="dona-contenedor">
      <div className="inicio-dona">
        <svg viewBox="0 0 120 120" width="150" height="150" role="img" aria-label="Ventas del mes por categoría">
          <circle cx="60" cy="60" r={RADIO} fill="none" stroke="#242831" strokeWidth="16" />
          {arcos.map((a) => (
            <circle
              key={a.nombre}
              cx="60"
              cy="60"
              r={RADIO}
              fill="none"
              stroke={a.color}
              strokeWidth="16"
              strokeDasharray={`${a.parte * LARGO} ${LARGO}`}
              strokeDashoffset={-a.inicio * LARGO}
              transform="rotate(-90 60 60)"
            />
          ))}
        </svg>
        <span>{dinero(total, moneda)}</span>
      </div>
      <ul className="dona-leyenda">
        {filas.map((f, i) => (
          <li key={f.nombre}>
            <i style={{ background: COLORES[i % COLORES.length] }} aria-hidden="true" />
            <span>{f.nombre}</span>
            <b>{Number(f.porcentaje).toLocaleString('es-PE', { maximumFractionDigits: 1 })} %</b>
          </li>
        ))}
      </ul>
    </div>
  )
}
