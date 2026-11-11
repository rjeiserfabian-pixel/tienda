/** Elige las series que vuelven: tantas como unidades se devuelven, de las que se vendieron. */
export default function SeriesDevueltas({ linea, n, elegidas, onCambio, disabled = false }) {
  const alternar = (serie) => onCambio(elegidas.includes(serie) ? elegidas.filter((x) => x !== serie) : [...elegidas, serie])
  return (
    <div className="nota-series" role="group" aria-label={`Series de ${linea.descripcion}`}>
      <span className="sub-texto">
        Series que vuelven ({elegidas.length}/{n}):
      </span>
      {linea.series.map((s) => (
        <label key={s}>
          <input type="checkbox" checked={elegidas.includes(s)} disabled={disabled} onChange={() => alternar(s)} /> {s}
        </label>
      ))}
    </div>
  )
}
