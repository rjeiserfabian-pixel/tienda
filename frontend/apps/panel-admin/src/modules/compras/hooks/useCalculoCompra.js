import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api, mensajeDeError } from '../../../core/api/client'
import { useDebounce } from '../../../shared/hooks/useDebounce'

/**
 * Vista previa de la compra: el servidor calcula totales, IGV, costo por línea y cuotas sin guardar
 * nada (es la misma cuenta que hará al registrar, así lo que se ve es lo que se guarda).
 * Se pide con 450 ms de retraso para no calcular en cada tecla y se cancela si el borrador cambia.
 */
export function useCalculoCompra(cuerpo, activo) {
  const texto = useDebounce(JSON.stringify(cuerpo), 450)
  const esperando = texto !== JSON.stringify(cuerpo)
  const consulta = useQuery({
    queryKey: ['compras', 'calcular', texto],
    queryFn: ({ signal }) => api.post('/compras/calcular/', JSON.parse(texto), { signal }).then((r) => r.data),
    enabled: activo,
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 30_000,
  })
  return {
    datos: activo ? consulta.data : undefined,
    calculando: activo && (esperando || consulta.isFetching),
    // Un error del cálculo no es un fallo de la pantalla: se muestra como aviso (p. ej. «el tipo de cambio…»).
    error: activo && consulta.isError && !esperando ? mensajeDeError(consulta.error) : '',
  }
}
