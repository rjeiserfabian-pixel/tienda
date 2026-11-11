import { Icono } from './IconosPanel'
import './listados.css'

const TAMANOS_POR_DEFECTO = [10, 25, 50, 100]

/** Números de página a mostrar: siempre la primera y la última, y una ventana alrededor de la actual. */
function paginasVisibles(actual, total) {
  const conjunto = new Set([1, total, actual - 1, actual, actual + 1])
  if (actual <= 3) [2, 3, 4].forEach((n) => conjunto.add(n))
  if (actual >= total - 2) [total - 1, total - 2, total - 3].forEach((n) => conjunto.add(n))
  const ordenadas = [...conjunto].filter((n) => n >= 1 && n <= total).sort((a, b) => a - b)
  return ordenadas.flatMap((n, i) => (i > 0 && n - ordenadas[i - 1] > 1 ? ['…', n] : [n]))
}

/** Paginación de tabla: rango mostrado, tamaño de página y números. `total` es el `count` del backend. */
export default function Paginacion({ pagina, tamano, total, onPagina, onTamano, tamanos = TAMANOS_POR_DEFECTO }) {
  const paginas = Math.max(1, Math.ceil(total / tamano))
  const desde = total === 0 ? 0 : (pagina - 1) * tamano + 1
  const hasta = Math.min(pagina * tamano, total)

  return (
    <nav className="paginacion-tabla" aria-label="Paginación">
      <span className="paginacion-rango">
        Mostrando {desde} - {hasta} de {total} registros
      </span>
      <div className="paginacion-controles">
        <label className="paginacion-tamano">
          Filas
          <select value={tamano} onChange={(e) => onTamano(Number(e.target.value))}>
            {tamanos.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="pagina-boton"
          disabled={pagina <= 1}
          onClick={() => onPagina(pagina - 1)}
          aria-label="Página anterior"
        >
          <Icono nombre="chevronIzq" tam={18} />
        </button>
        {paginasVisibles(pagina, paginas).map((n, i) =>
          n === '…' ? (
            <span key={`e${i}`} className="pagina-puntos" aria-hidden="true">
              …
            </span>
          ) : (
            <button
              key={n}
              type="button"
              className={`pagina-boton${n === pagina ? ' activa' : ''}`}
              aria-current={n === pagina ? 'page' : undefined}
              aria-label={`Página ${n}`}
              onClick={() => onPagina(n)}
            >
              {n}
            </button>
          ),
        )}
        <button
          type="button"
          className="pagina-boton"
          disabled={pagina >= paginas}
          onClick={() => onPagina(pagina + 1)}
          aria-label="Página siguiente"
        >
          <Icono nombre="chevron" tam={18} />
        </button>
      </div>
    </nav>
  )
}
