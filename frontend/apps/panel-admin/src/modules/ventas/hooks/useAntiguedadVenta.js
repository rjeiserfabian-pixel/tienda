import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { api } from '../../../core/api/client'

/**
 * Aviso de stock antiguo para el carrito del mostrador: por cada producto con unidades que pasan los
 * días configurados, desde cuándo ingresó lo más viejo. Es solo una nota (sin costos): no bloquea nada.
 * Devuelve un mapa `"empresa:almacen:producto" → aviso`.
 */
export function useAntiguedadVenta(lineas) {
  const claves = useMemo(() => {
    const unicas = new Set()
    for (const l of lineas) {
      if (l.ficha?.controla_stock && l.empresa && l.almacen) unicas.add(`${l.empresa}:${l.almacen}:${l.ficha.id}`)
    }
    return [...unicas].sort().slice(0, 50)
  }, [lineas])

  const consulta = useQuery({
    queryKey: ['antiguedad-venta', claves],
    queryFn: ({ signal }) => api.get('/inventario/antiguedad/venta/', { params: { items: claves.join(',') }, signal }).then((r) => r.data),
    enabled: claves.length > 0,
    staleTime: 60_000,
    retry: false, // si falla, el carrito sigue igual: es solo una ayuda
  })

  return useMemo(() => {
    const mapa = {}
    for (const a of consulta.data ?? []) mapa[`${a.empresa}:${a.almacen}:${a.producto}`] = a
    return mapa
  }, [consulta.data])
}

/** «03/07» a partir de «2026-07-03». */
export const diaMes = (iso) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}` : '')
