import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'
import { useMutacion } from '../../../shared/hooks/useMutacion'

const URL = '/rrhh/asistencia'

/** La grilla del mes (trabajadores × días con totales). Se conserva la anterior mientras llega la nueva. */
export function useGrillaAsistencia({ empresa, anio, mes, q }) {
  const params = { empresa, anio, mes, ...(q ? { q } : {}) }
  return useQuery({
    queryKey: ['asistencia', 'grilla', params],
    queryFn: ({ signal }) => api.get(`${URL}/`, { params, signal }).then((r) => r.data),
    enabled: Boolean(empresa),
    placeholderData: keepPreviousData,
  })
}

/** Una acción de escritura: `dia`, `rango` o `completar`. */
export function useAccionAsistencia(accion, { exito, alExito } = {}) {
  return useMutacion({
    mutationFn: (cuerpo) => api.post(`${URL}/${accion}/`, cuerpo).then((r) => r.data),
    invalidar: [['asistencia']],
    exito,
    alExito,
    avisarError: false,
  })
}
