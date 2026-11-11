import { dinero, DENOMINACIONES, esMoneda, resultadoDeConteo, totalContado } from '../caja'

const GRUPOS = [
  ['Billetes', (d, moneda) => !esMoneda(d, moneda)],
  ['Monedas', (d, moneda) => esMoneda(d, moneda)],
]

/**
 * Conteo del efectivo por billetes y monedas. Muestra lo contado frente a lo que el sistema espera
 * y cómo queda: cuadra, sobra o falta.
 */
export default function ConteoEfectivo({ moneda, conteo, onCambio, esperado, deshabilitado, error }) {
  const contado = totalContado(conteo)
  const resultado = esperado === undefined ? null : resultadoDeConteo(contado, esperado)
  const cambiar = (denominacion, valor) => onCambio({ ...conteo, [denominacion]: valor.replace(/\D/g, '').slice(0, 7) })

  return (
    <div className="conteo">
      <div className="conteo-grupos">
        {GRUPOS.map(([titulo, incluye]) => {
          const filas = DENOMINACIONES[moneda].filter((d) => incluye(d, moneda))
          if (filas.length === 0) return null
          return (
            <section key={titulo} className="conteo-grupo" aria-label={titulo}>
              <h4>{titulo}</h4>
              {filas.map((d) => {
                const cantidad = Number.parseInt(conteo[d], 10) || 0
                return (
                  <div key={d} className="conteo-fila">
                    <label htmlFor={`conteo-${d}`}>{dinero(d, moneda)}</label>
                    <input id={`conteo-${d}`} inputMode="numeric" autoComplete="off" placeholder="0" aria-label={`Cantidad de ${dinero(d, moneda)}`} disabled={deshabilitado} value={conteo[d] ?? ''} onChange={(e) => cambiar(d, e.target.value)} />
                    <output htmlFor={`conteo-${d}`}>{cantidad > 0 ? dinero(Math.round(Number(d) * 100) * cantidad / 100, moneda) : ''}</output>
                  </div>
                )
              })}
            </section>
          )
        })}
      </div>
      <dl className="conteo-resumen" aria-live="polite">
        {resultado && (
          <div>
            <dt>El sistema espera</dt>
            <dd>{dinero(esperado, moneda)}</dd>
          </div>
        )}
        <div>
          <dt>Contado</dt>
          <dd>{dinero(contado, moneda)}</dd>
        </div>
        {resultado && (
          <div data-tono={resultado.tipo}>
            <dt>{resultado.tipo === 'cuadra' ? 'Resultado' : resultado.tipo === 'sobra' ? 'Sobra' : 'Falta'}</dt>
            <dd>{resultado.tipo === 'cuadra' ? 'Cuadra' : dinero(Math.abs(resultado.diferencia), moneda)}</dd>
          </div>
        )}
      </dl>
      {error && (
        <p role="alert" className="campo-error">
          {error}
        </p>
      )}
    </div>
  )
}
