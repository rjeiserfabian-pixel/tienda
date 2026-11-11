import { useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'

/** Catálogo completo de permisos (cambia solo con un despliegue: se conserva 10 minutos). */
export function useCatalogoPermisos() {
  return useQuery({
    queryKey: ['catalogo-permisos'],
    queryFn: ({ signal }) => api.get('/seguridad/permisos/catalogo/', { signal }).then((r) => r.data),
    staleTime: 10 * 60_000,
  })
}

/** Roles de la organización para los selectores (máximo 100: un selector no necesita más). */
export function useRolesParaSelector() {
  return useQuery({
    queryKey: ['roles', 'selector'],
    queryFn: ({ signal }) =>
      api.get('/seguridad/roles/', { params: { page_size: 100 }, signal }).then((r) => r.data.results),
    staleTime: 60_000,
  })
}

export const ALCANCES = [
  ['PROPIO', 'Solo lo propio'],
  ['ASIGNADO', 'Lo asignado'],
  ['SUCURSAL', 'Sus sucursales'],
  ['EMPRESA', 'Toda la empresa'],
  ['ORGANIZACION', 'Toda la organización'],
]
