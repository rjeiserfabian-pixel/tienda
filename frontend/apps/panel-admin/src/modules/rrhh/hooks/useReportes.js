import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'

/** El reporte pedido en pantalla (se consulta solo cuando hay un pedido armado). */
export function useReporte(pedido) {
  return useQuery({
    queryKey: ['rrhh-reportes', pedido],
    queryFn: ({ signal }) => api.get(`/rrhh/reportes/${pedido.tipo}/`, { params: pedido.params, signal }).then((r) => r.data),
    enabled: Boolean(pedido),
    placeholderData: keepPreviousData,
    staleTime: 0,
    retry: 0,
  })
}

/** Lo propio del trabajador: sus boletas, su saldo de vacaciones y sus adelantos. */
export function useMiResumen(empresa) {
  return useQuery({
    queryKey: ['rrhh-mi', 'resumen', empresa],
    queryFn: ({ signal }) => api.get('/rrhh/mi/resumen/', { params: { empresa }, signal }).then((r) => r.data),
    enabled: Boolean(empresa),
    retry: 0,
  })
}
