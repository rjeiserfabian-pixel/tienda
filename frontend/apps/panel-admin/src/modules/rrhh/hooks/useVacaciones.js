import { useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'
import { useMutacion } from '../../../shared/hooks/useMutacion'

const URL = '/rrhh/vacaciones'

/** Vacaciones registradas de un trabajador (las más recientes primero). */
export function useVacacionesDe(empresa, personal) {
  return useQuery({
    queryKey: ['vacaciones', 'historial', empresa, personal],
    queryFn: ({ signal }) => api.get(`${URL}/`, { params: { empresa, personal, page_size: 50 }, signal }).then((r) => r.data),
    enabled: Boolean(empresa) && Boolean(personal),
  })
}

export function useRegistrarVacaciones({ exito, alExito } = {}) {
  return useMutacion({
    mutationFn: (datos) => api.post(`${URL}/`, datos).then((r) => r.data),
    invalidar: [['vacaciones'], ['asistencia']],
    exito,
    alExito,
    avisarError: false,
  })
}

export function useAnularVacaciones({ exito, alExito } = {}) {
  return useMutacion({
    mutationFn: ({ id, motivo }) => api.post(`${URL}/${id}/anular/`, { motivo }).then((r) => r.data),
    invalidar: [['vacaciones'], ['asistencia']],
    exito,
    alExito,
    avisarError: false,
  })
}
