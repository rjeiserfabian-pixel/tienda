import { cantidad } from '../inventario'
import '../tomas.css'

function Barra({ valor, total, etiqueta }) {
  const porcentaje = total ? Math.round((valor / total) * 100) : 0
  return (
    <div className="toma-barra" role="progressbar" aria-label={etiqueta} aria-valuemin={0} aria-valuemax={100} aria-valuenow={porcentaje}>
      <span style={{ width: `${porcentaje}%` }} />
    </div>
  )
}

/**
 * Avance del conteo: cuántos productos van, cuántos faltan y cómo va cada categoría.
 * No muestra faltantes ni sobrantes: eso es el resultado, que ve quien aprueba.
 */
export default function TomaAvance({ avance, onCategoria }) {
  const { total, contados, por_contar: porContar, por_recontar: porRecontar, por_anotar: porAnotar, porcentaje_avance: porcentaje, por_categoria: categorias } = avance

  return (
    <section className="toma-panel" aria-label="Avance del conteo">
      <header className="toma-panel-cabecera">
        <h3>Avance</h3>
        <strong className="toma-porcentaje">{cantidad(porcentaje)} %</strong>
      </header>
      <Barra valor={contados} total={total} etiqueta="Productos contados" />

      <dl className="toma-resumen">
        <div>
          <dt>Productos en la toma</dt>
          <dd>{cantidad(total)}</dd>
        </div>
        <div data-tono="sobra">
          <dt>Contados</dt>
          <dd>{cantidad(contados)}</dd>
        </div>
        <div data-tono={porContar ? 'falta' : undefined}>
          <dt>Por contar</dt>
          <dd>{cantidad(porContar)}</dd>
        </div>
        {porRecontar > 0 && (
          <div data-tono="aviso">
            <dt>Por recontar</dt>
            <dd>{cantidad(porRecontar)}</dd>
          </div>
        )}
        {porAnotar > 0 && (
          <div data-tono="aviso">
            <dt>Con diferencia, sin nota</dt>
            <dd>{cantidad(porAnotar)}</dd>
          </div>
        )}
      </dl>

      {categorias.length > 0 && (
        <details className="toma-categorias-avance">
          <summary>Avance por categoría ({categorias.length})</summary>
          <ul>
            {categorias.map((c) => (
              <li key={c.categoria_id}>
                <button type="button" className="enlace-boton" onClick={() => onCategoria?.(c.categoria_id)} title="Ver solo esta categoría">
                  {c.categoria}
                </button>
                <span className="celda-suave">
                  {cantidad(c.contados)} de {cantidad(c.total)}
                </span>
                <Barra valor={c.contados} total={c.total} etiqueta={`Avance de ${c.categoria}`} />
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}
