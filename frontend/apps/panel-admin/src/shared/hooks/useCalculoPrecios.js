import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { api } from '../../core/api/client'
import { MODOS_PRECIO, porcentajeDesdePrecio, precioDesdePorcentaje } from '../../modules/almacen/utilidades'

/**
 * Cómo calcula los precios la organización: por UTILIDAD (sobre el costo) o por MARGEN (sobre el
 * precio). Devuelve el modo, los textos para las pantallas y las dos conversiones ya ajustadas:
 * `aPrecio(costo, porcentaje)` y `aPorcentaje(costo, precio)`. Mientras carga, usa utilidad.
 */
export function useCalculoPrecios() {
  const consulta = useQuery({
    queryKey: ['organizacion'],
    queryFn: ({ signal }) => api.get('/organizacion/', { signal }).then((r) => r.data),
    staleTime: 5 * 60_000,
  })
  const modo = consulta.data?.calculo_precios === 'MARGEN' ? 'MARGEN' : 'UTILIDAD'
  return useMemo(
    () => ({
      modo,
      ...MODOS_PRECIO[modo],
      aPrecio: (costo, porcentaje) => precioDesdePorcentaje(costo, porcentaje, modo),
      aPorcentaje: (costo, precio) => porcentajeDesdePrecio(costo, precio, modo),
    }),
    [modo],
  )
}
