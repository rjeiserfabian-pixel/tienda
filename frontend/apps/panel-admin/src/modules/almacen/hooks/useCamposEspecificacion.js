import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { api } from '../../../core/api/client'
import { campoActivo } from '../../mantenimiento/especificaciones'

/**
 * Los datos técnicos vigentes de una categoría (RAM, DPI, socket…), en el orden de la plantilla.
 * Comparte la clave de consulta con el editor de Familias y categorías: al guardar allá, se refresca aquí.
 */
export function useCamposEspecificacion(categoriaId) {
  const id = categoriaId ? Number(categoriaId) : null
  const consulta = useQuery({
    queryKey: ['categorias', 'especificaciones', id],
    queryFn: ({ signal }) => api.get(`/mantenimiento/categorias/${id}/especificaciones/`, { signal }).then((r) => r.data),
    enabled: Boolean(id),
    staleTime: 30_000,
  })
  const activos = useMemo(() => (consulta.data ?? []).filter(campoActivo), [consulta.data])
  return { consulta, activos, listos: consulta.isSuccess }
}
