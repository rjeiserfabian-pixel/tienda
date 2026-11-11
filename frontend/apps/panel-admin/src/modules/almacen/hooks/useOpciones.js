import { useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'

/** Opciones activas de un catálogo (familias, categorías, marcas, unidades, listas de precio). */
export function useOpciones(url, params = {}, { enabled = true } = {}) {
  return useQuery({
    queryKey: ['opciones', url, params],
    queryFn: ({ signal }) => api.get(url, { params: { estado: 'ACTIVO', page_size: 100, ...params }, signal }).then((r) => r.data.results),
    enabled,
    staleTime: 30_000,
  })
}
