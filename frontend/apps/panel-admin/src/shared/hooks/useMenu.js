import { useQuery } from '@tanstack/react-query'
import { api } from '../../core/api/client'
import { useEmpresas } from '../contexts/EmpresasContext'

/** Menú dinámico del usuario (solo los módulos que puede ver). */
export function useMenu() {
  const { empresaActivaId } = useEmpresas()
  return useQuery({
    // La clave incluye la empresa: al cambiarla se vuelve a consultar.
    queryKey: ['menu', empresaActivaId],
    queryFn: ({ signal }) => api.get('/seguridad/menu/', { signal }).then((r) => r.data),
    staleTime: 60_000,
  })
}
