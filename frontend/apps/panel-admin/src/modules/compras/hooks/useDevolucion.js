import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api, mensajeDeError } from '../../../core/api/client'
import { useDebounce } from '../../../shared/hooks/useDebounce'

/** Lo que todavía se puede devolver de cada línea de una compra, con su deuda pendiente. */
export function usePorDevolver(compraId) {
  return useQuery({
    queryKey: ['compras', 'por-devolver', String(compraId)],
    queryFn: ({ signal }) => api.get(`/compras/${compraId}/por-devolver/`, { signal }).then((r) => r.data),
    staleTime: 0,
  })
}

/**
 * Vista previa de la devolución: el servidor calcula importes, IGV y a dónde iría el dinero sin
 * registrar nada (es la misma cuenta que hará al registrar). Se pide con 450 ms de retraso para no
 * calcular en cada tecla.
 */
export function useCalculoDevolucion(cuerpo, activo) {
  const texto = useDebounce(JSON.stringify(cuerpo), 450)
  const esperando = texto !== JSON.stringify(cuerpo)
  const consulta = useQuery({
    queryKey: ['compras', 'devolucion-calculo', texto],
    queryFn: ({ signal }) => api.post('/compras/devoluciones/calcular/', JSON.parse(texto), { signal }).then((r) => r.data),
    enabled: activo,
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 30_000,
  })
  return {
    datos: activo ? consulta.data : undefined,
    calculando: activo && (esperando || consulta.isFetching),
    // Un error del cálculo no es un fallo de la pantalla: se muestra como aviso («solo se puede devolver 4»).
    error: activo && consulta.isError && !esperando ? mensajeDeError(consulta.error) : '',
  }
}
