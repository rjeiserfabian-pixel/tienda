import { useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'
import { useMutacion } from '../../../shared/hooks/useMutacion'

const URL = '/rrhh/adelantos'

/** Una entrega con su detalle (cuotas, motivo, anulación). */
export function useAdelanto(id) {
  return useQuery({
    queryKey: ['adelantos', 'ficha', id],
    queryFn: ({ signal }) => api.get(`${URL}/${id}/`, { signal }).then((r) => r.data),
  })
}

/** Cajas en soles, métodos de pago y trabajadores con contrato vigente para entregar un adelanto. */
export function useOpcionesAdelanto(empresa) {
  return useQuery({
    queryKey: ['adelantos', 'opciones', empresa],
    queryFn: ({ signal }) => api.get(`${URL}/opciones/`, { params: { empresa }, signal }).then((r) => r.data),
    enabled: Boolean(empresa),
    staleTime: 30_000,
  })
}

// Entregar o anular mueve dinero de Caja: se refrescan también sus consultas.
const INVALIDAR = [['adelantos'], ['caja']]

/** Entrega un adelanto o préstamo. Viaja con clave de idempotencia: un reintento no entrega dos veces. */
export function useEntregarAdelanto({ exito, alExito } = {}) {
  return useMutacion({
    mutationFn: ({ datos, llave }) => api.post(`${URL}/`, datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: INVALIDAR,
    exito,
    alExito,
    avisarError: false,
  })
}

export function useAnularAdelanto(id, { exito, alExito } = {}) {
  return useMutacion({
    mutationFn: (motivo) => api.post(`${URL}/${id}/anular/`, { motivo }).then((r) => r.data),
    invalidar: INVALIDAR,
    exito,
    alExito,
    avisarError: false,
  })
}
