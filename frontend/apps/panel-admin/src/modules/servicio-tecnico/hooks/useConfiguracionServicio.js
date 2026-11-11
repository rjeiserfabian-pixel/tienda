import { useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'

/** Catálogos activos, técnicos y sucursales de la empresa para armar la pantalla de ingreso. */
export function useConfiguracionServicio(empresaId) {
  return useQuery({
    queryKey: ['servicio', 'configuracion', empresaId],
    queryFn: ({ signal }) => api.get('/servicio-tecnico/configuracion/', { params: { empresa: empresaId }, signal }).then((r) => r.data),
    enabled: Boolean(empresaId),
    staleTime: 60_000,
  })
}
