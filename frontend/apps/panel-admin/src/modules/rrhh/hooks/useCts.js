import { useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'
import { useMutacion } from '../../../shared/hooks/useMutacion'

const URL = '/rrhh/cts'

/** Un cálculo de CTS con lo que le toca a cada trabajador. */
export function useCts(id) {
  return useQuery({
    queryKey: ['cts', 'ficha', id],
    queryFn: ({ signal }) => api.get(`${URL}/${id}/`, { signal }).then((r) => r.data),
  })
}

/** Cajas o cuentas en soles y métodos de pago para el depósito. */
export function useOpcionesDeposito(id) {
  return useQuery({
    queryKey: ['cts', 'opciones', id],
    queryFn: ({ signal }) => api.get(`${URL}/${id}/opciones-pago/`, { signal }).then((r) => r.data),
    staleTime: 30_000,
  })
}

export function useCalcularCts({ exito, alExito } = {}) {
  return useMutacion({
    mutationFn: (datos) => api.post(`${URL}/`, datos, { timeout: 60_000 }).then((r) => r.data),
    invalidar: [['cts']],
    exito,
    alExito,
    avisarError: false,
  })
}

// Depositar o anular mueve dinero de Caja: se refrescan también sus consultas.
const INVALIDAR = [['cts'], ['caja']]

/** Una acción sobre un cálculo: `recalcular` o `anular-deposito`. */
export function useAccionCts(id, accion, { exito, alExito } = {}) {
  return useMutacion({
    mutationFn: (cuerpo) => api.post(`${URL}/${id}/${accion}/`, cuerpo ?? {}, { timeout: 60_000 }).then((r) => r.data),
    invalidar: INVALIDAR,
    exito,
    alExito,
    avisarError: false,
  })
}

/** Registra el depósito. Lleva clave de idempotencia: un reintento no deposita dos veces. */
export function useDepositarCts(id, { exito, alExito } = {}) {
  return useMutacion({
    mutationFn: ({ datos, llave }) => api.post(`${URL}/${id}/depositar/`, datos, { headers: { 'Idempotency-Key': llave }, timeout: 60_000 }).then((r) => r.data),
    invalidar: INVALIDAR,
    exito,
    alExito,
    avisarError: false,
  })
}

export function useDescartarCts(id, { exito, alExito } = {}) {
  return useMutacion({
    mutationFn: () => api.delete(`${URL}/${id}/`),
    invalidar: [['cts', 'lista']],
    exito,
    alExito,
    avisarError: false,
  })
}
