import { useState } from 'react'
import Campo from '../../../shared/components/Campo'
import { useSeriesEnStock } from '../hooks/useToma'
import { normalizarSerie, parsearSeries } from '../inventario'
import '../tomas.css'

/**
 * Las series o IMEI de un producto con diferencia: las que SALEN (faltante) o las que ENTRAN (sobrante).
 * En un faltante se pueden elegir de las que el sistema tiene en stock; en un sobrante se escriben o pegan.
 */
export default function TomaSeriesAjuste({ fila, empresa, almacen, texto, onTexto, error }) {
  const [eligiendo, setEligiendo] = useState(false)
  const sale = fila.tipo === 'SALIDA'
  const necesarias = Number(fila.cantidad)
  const escritas = parsearSeries(texto)
  const enStock = useSeriesEnStock({ empresa, almacen, producto: fila.producto, enabled: sale && eligiendo })

  const alternar = (numero) => {
    const serie = normalizarSerie(numero)
    onTexto(escritas.includes(serie) ? escritas.filter((s) => s !== serie).join('\n') : [...escritas, serie].join('\n'))
  }

  return (
    <div className="toma-series">
      <Campo
        etiqueta={`${fila.producto_nombre}: series que ${sale ? 'salen' : 'entran'} (${necesarias})`}
        requerido
        error={error}
        ayuda={`Una por línea, o separadas por coma. Llevas ${escritas.length} de ${necesarias}.`}
      >
        {(p) => <textarea {...p} rows={Math.min(6, Math.max(2, necesarias))} value={texto} onChange={(e) => onTexto(e.target.value)} />}
      </Campo>
      {sale && (
        <>
          <button type="button" className="enlace-boton" onClick={() => setEligiendo((v) => !v)}>
            {eligiendo ? 'Ocultar las series en stock' : 'Elegir de las series que hay en stock'}
          </button>
          {eligiendo && enStock.isLoading && <p className="celda-suave">Cargando series…</p>}
          {eligiendo && enStock.isError && (
            <p role="alert" className="campo-error">
              No se pudieron cargar las series.
            </p>
          )}
          {eligiendo && enStock.data && (
            <ul className="toma-series-chips" aria-label="Series en stock">
              {enStock.data.results.map((s) => (
                <li key={s.id}>
                  <button type="button" className={escritas.includes(s.numero) ? 'primario' : undefined} aria-pressed={escritas.includes(s.numero)} onClick={() => alternar(s.numero)}>
                    {s.numero}
                  </button>
                </li>
              ))}
              {enStock.data.results.length === 0 && <li className="celda-suave">No hay series en stock de este producto.</li>}
            </ul>
          )}
        </>
      )}
    </div>
  )
}
