import { useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'

const pedir = (empresaId, sucursal) => ({
  queryKey: ['ventas', 'configuracion', empresaId, sucursal ?? null],
  queryFn: ({ signal }) => api.get('/ventas/configuracion/', { params: { empresa: empresaId, ...(sucursal ? { sucursal } : {}) }, signal }).then((r) => r.data),
  staleTime: 30_000,
  placeholderData: (previo) => previo,
})

/**
 * Todo lo que la pantalla de venta necesita: empresas, listas, métodos de pago, permisos y vendedores.
 * Si no se elige tienda se usa la primera de la empresa: se pide una vez para conocerlas y otra con
 * la tienda definitiva, porque a qué caja entra cada cobro depende de la tienda.
 * Devuelve la consulta y la tienda en uso (`sucursal`).
 */
export function useConfiguracionVenta(empresaId, sucursalElegida = null) {
  const activo = Boolean(empresaId)
  const inicial = useQuery({ ...pedir(empresaId, sucursalElegida), enabled: activo })
  const tiendas = inicial.data?.sucursales ?? []
  const sucursal = sucursalElegida && tiendas.some((s) => s.id === sucursalElegida) ? sucursalElegida : (tiendas[0]?.id ?? null)
  const hayOtra = sucursal !== (sucursalElegida ?? null)
  const definitiva = useQuery({ ...pedir(empresaId, sucursal), enabled: activo && inicial.isSuccess && hayOtra })
  const consulta = hayOtra ? definitiva : inicial
  return { ...consulta, sucursal }
}
