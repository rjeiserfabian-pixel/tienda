import { useState } from 'react'
import Campo from '../../../shared/components/Campo'
import { cantidad as formatoCantidad } from '../../almacen/inventario'
import { aNumero } from '../../almacen/utilidades'
import SeriesDevolucionModal from './SeriesDevolucionModal'

/**
 * Qué se devuelve de cada línea de la compra: cuánto se compró, cuánto ya se devolvió y cuánto se
 * devuelve ahora. Los productos con serie se devuelven eligiendo las series que siguen en el almacén.
 */
export default function DevolverLineas({ compra, lineas, filas, errores, onFila, disabled }) {
  const [serieDe, setSerieDe] = useState(null) // línea cuyas series se están eligiendo
  const productoDe = (linea) => compra.lineas.find((l) => l.id === linea.linea)

  const devolverTodo = (linea) => {
    if (linea.lleva_serie) return setSerieDe(linea)
    return onFila(linea.linea, { cantidad: String(linea.pendiente) })
  }
  const todasLasLineas = () => {
    for (const l of lineas) {
      if (l.lleva_serie || aNumero(l.pendiente) <= 0) continue
      onFila(l.linea, { cantidad: String(l.pendiente) })
    }
  }

  return (
    <>
      <div className="marco-tabla compra-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th>Producto</th>
              <th className="num">Comprado</th>
              <th className="num">Ya devuelto</th>
              <th className="num">Se puede devolver</th>
              <th>Devolver ahora</th>
            </tr>
          </thead>
          <tbody>
            {lineas.map((l) => {
              const producto = productoDe(l)
              const fila = filas[l.linea] ?? {}
              const sinSaldo = aNumero(l.pendiente) <= 0
              return (
                <tr key={l.linea}>
                  <td className="col-texto compra-celda-producto">
                    {producto?.producto_nombre ?? `Línea ${l.orden}`}
                    <span className="sub-texto">
                      {producto?.producto_codigo} · {l.unidad}
                      {l.lleva_serie ? ' · con serie' : ''}
                    </span>
                  </td>
                  <td className="num">{formatoCantidad(l.comprado)}</td>
                  <td className="num">{formatoCantidad(l.devuelto)}</td>
                  <td className="num">{formatoCantidad(l.pendiente)}</td>
                  <td>
                    {sinSaldo ? (
                      <span className="celda-suave">Ya se devolvió todo</span>
                    ) : l.lleva_serie ? (
                      <button type="button" className="boton-cabecera" disabled={disabled} onClick={() => setSerieDe(l)}>
                        {fila.series?.length ? `${fila.series.length} ${fila.series.length === 1 ? 'serie elegida' : 'series elegidas'}` : 'Elegir series'}
                      </button>
                    ) : (
                      <span className="dev-cantidad">
                        <Campo etiqueta={`Cantidad a devolver de ${producto?.producto_nombre ?? 'la línea'}`} error={errores[l.linea]}>
                          {(p) => <input {...p} inputMode="decimal" placeholder="0" value={fila.cantidad ?? ''} disabled={disabled} onChange={(e) => onFila(l.linea, { cantidad: e.target.value })} />}
                        </Campo>
                        <button type="button" disabled={disabled} onClick={() => devolverTodo(l)}>
                          Todo
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="compra-pagos-pie">
        <button type="button" className="boton-cabecera" disabled={disabled} onClick={todasLasLineas}>
          Devolver todo lo pendiente
        </button>
      </div>
      {serieDe && (
        <SeriesDevolucionModal
          producto={productoDe(serieDe)?.producto_nombre}
          disponibles={serieDe.series_disponibles}
          elegidas={filas[serieDe.linea]?.series ?? []}
          pendiente={Math.floor(aNumero(serieDe.pendiente) ?? 0)}
          onGuardar={(series) => {
            onFila(serieDe.linea, { series })
            setSerieDe(null)
          }}
          onCerrar={() => setSerieDe(null)}
        />
      )}
    </>
  )
}
