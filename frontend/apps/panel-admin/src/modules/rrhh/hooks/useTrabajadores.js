import { useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'
import { useMutacion } from '../../../shared/hooks/useMutacion'

const URL = '/rrhh'
// Todo lo del trabajador cuelga de ['trabajadores']: invalidar esa clave refresca lista y ficha.
export const claveTrabajador = (id) => ['trabajadores', 'ficha', id]

/** Ficha laboral completa (datos, contratos y, con permiso, sueldos). */
export function useTrabajador(id) {
  return useQuery({
    queryKey: claveTrabajador(id),
    queryFn: ({ signal }) => api.get(`${URL}/trabajadores/${id}/`, { signal }).then((r) => r.data),
  })
}

/** Regímenes laborales activos (para elegir el del contrato). */
export function useRegimenes() {
  return useQuery({
    queryKey: ['regimenes', 'opciones'],
    queryFn: ({ signal }) =>
      api.get(`${URL}/regimenes/`, { params: { estado: 'ACTIVO', page_size: 100 }, signal }).then((r) => r.data.results),
    staleTime: 60_000,
  })
}

const OPCIONES = { invalidar: [['trabajadores']], avisarError: false }

/** Guarda lo que se envíe de los datos laborales (solo cambia lo enviado). */
export function useGuardarDatosLaborales(id, { exito, alExito } = {}) {
  return useMutacion({
    ...OPCIONES,
    mutationFn: (cuerpo) => api.patch(`${URL}/trabajadores/${id}/datos-laborales/`, cuerpo).then((r) => r.data),
    exito,
    alExito,
  })
}

/** Registra un contrato nuevo (con su sueldo inicial). */
export function useCrearContrato(id, { exito, alExito } = {}) {
  return useMutacion({
    ...OPCIONES,
    mutationFn: (cuerpo) => api.post(`${URL}/trabajadores/${id}/contratos/`, cuerpo).then((r) => r.data),
    exito,
    alExito,
  })
}

/** Corrige un contrato vigente. */
export function useEditarContrato(contratoId, { exito, alExito } = {}) {
  return useMutacion({
    ...OPCIONES,
    mutationFn: (cuerpo) => api.patch(`${URL}/contratos/${contratoId}/`, cuerpo).then((r) => r.data),
    exito,
    alExito,
  })
}

/** Una acción del contrato: `finalizar` o `sueldos` (cambio de sueldo). */
export function useAccionContrato(contratoId, accion, { exito, alExito } = {}) {
  return useMutacion({
    ...OPCIONES,
    mutationFn: (cuerpo) => api.post(`${URL}/contratos/${contratoId}/${accion}/`, cuerpo).then((r) => r.data),
    exito,
    alExito,
  })
}
