import { useQuery } from '@tanstack/react-query'
import { api } from '../../core/api/client'

/** Consulta /salud/ del backend (con caché y cancelación automática de React Query). */
export function useSalud() {
  return useQuery({
    queryKey: ['salud'],
    queryFn: ({ signal }) => api.get('/salud/', { signal }).then((r) => r.data),
    retry: false,
    staleTime: 30_000,
  })
}
