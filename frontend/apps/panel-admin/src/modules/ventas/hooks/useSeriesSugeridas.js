import { useEffect, useRef } from 'react'
import { api } from '../../../core/api/client'

/**
 * Productos con serie: al agregarlos (o cambiar la cantidad o la empresa que surte) propone las
 * series MÁS ANTIGUAS del almacén (primero en entrar, primero en salir) para no dejar stock viejo.
 * Es solo una propuesta: el vendedor puede abrir «Series» y poner otras. Si ya hay series en la
 * línea no se toca nada.
 */
export function useSeriesSugeridas(linea, onCambiar, activo) {
  const ultima = useRef(linea)
  ultima.current = linea
  const lleva = Boolean(linea.ficha.lleva_serie)
  const cantidad = Number(linea.cantidad)
  const sinSeries = linea.series.length === 0

  useEffect(() => {
    if (!lleva || !activo || !sinSeries || !linea.almacen || !Number.isInteger(cantidad) || cantidad < 1) return undefined
    const control = new AbortController()
    api
      .get('/ventas/series-sugeridas/', {
        params: { empresa: linea.empresa, surte: linea.empresa, almacen: linea.almacen, producto: linea.ficha.id, cantidad },
        signal: control.signal,
      })
      .then((r) => {
        const propuestas = r.data?.series ?? []
        const actual = ultima.current
        // Solo si la línea sigue igual (mismo producto y cantidad) y el vendedor no puso nada.
        if (propuestas.length === cantidad && actual.series.length === 0 && Number(actual.cantidad) === cantidad) {
          onCambiar({ ...actual, series: propuestas })
        }
      })
      .catch(() => {})
    return () => control.abort()
    // onCambiar cambia en cada render; la propuesta solo depende de estos datos
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lleva, activo, sinSeries, linea.empresa, linea.almacen, linea.ficha.id, cantidad])
}
