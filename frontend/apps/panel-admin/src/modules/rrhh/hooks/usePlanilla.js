import { useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'
import { useMutacion } from '../../../shared/hooks/useMutacion'

const URL = '/rrhh/planillas'

/** La planilla de un mes con una fila por trabajador y lo que hay que revisar. */
export function usePlanilla(id) {
  return useQuery({
    queryKey: ['planillas', 'ficha', id],
    queryFn: ({ signal }) => api.get(`${URL}/${id}/`, { signal }).then((r) => r.data),
  })
}

/** Los renglones de un trabajador en la planilla. */
export function usePlanillaTrabajador(planilla, detalle) {
  return useQuery({
    queryKey: ['planillas', 'trabajador', planilla, detalle],
    queryFn: ({ signal }) => api.get(`${URL}/${planilla}/trabajadores/${detalle}/`, { signal }).then((r) => r.data),
  })
}

/** Los conceptos que se pueden agregar a mano (bonos, comisiones, otros descuentos). */
export function useOpcionesPlanilla(empresa, habilitado) {
  return useQuery({
    queryKey: ['planillas', 'opciones', empresa],
    queryFn: ({ signal }) => api.get(`${URL}/opciones/`, { params: { empresa }, signal }).then((r) => r.data),
    enabled: Boolean(empresa) && habilitado,
    staleTime: 60_000,
  })
}

const INVALIDAR = [['planillas'], ['asistencia'], ['adelantos']]

/** Prepara la planilla de un mes. Lleva clave de idempotencia: un reintento no la repite. */
export function usePrepararPlanilla({ exito, alExito } = {}) {
  return useMutacion({
    mutationFn: ({ datos, llave }) => api.post(`${URL}/`, datos, { headers: { 'Idempotency-Key': llave }, timeout: 60_000 }).then((r) => r.data),
    invalidar: INVALIDAR,
    exito,
    alExito,
    avisarError: false,
  })
}

/** Una acción sobre una planilla: `recalcular`, `cerrar`, `reabrir`, `ajustes` o `diferir`. */
export function useAccionPlanilla(id, accion, { exito, alExito } = {}) {
  return useMutacion({
    mutationFn: (cuerpo) => api.post(`${URL}/${id}/${accion}/`, cuerpo ?? {}, { timeout: 60_000 }).then((r) => r.data),
    invalidar: INVALIDAR,
    exito,
    alExito,
    avisarError: false,
  })
}

export function useQuitarAjuste(id, { exito } = {}) {
  return useMutacion({
    mutationFn: (linea) => api.delete(`${URL}/${id}/ajustes/${linea}/`).then((r) => r.data),
    invalidar: INVALIDAR,
    exito,
    avisarError: false,
  })
}

export function useDescartarPlanilla(id, { exito, alExito } = {}) {
  return useMutacion({
    mutationFn: () => api.delete(`${URL}/${id}/`),
    // Solo las listas: la ficha de esta planilla ya no existe y no debe volver a pedirse.
    invalidar: [['planillas', 'lista'], ['asistencia']],
    exito,
    alExito,
    avisarError: false,
  })
}

/** Cajas o cuentas en soles y métodos de pago para pagar los sueldos. */
export function useOpcionesPago(planilla) {
  return useQuery({
    queryKey: ['planillas', 'opciones-pago', planilla],
    queryFn: ({ signal }) => api.get(`${URL}/${planilla}/opciones-pago/`, { signal }).then((r) => r.data),
    staleTime: 30_000,
  })
}

// Pagar o anular un pago mueve dinero de Caja: se refrescan también sus consultas.
const INVALIDAR_PAGO = [['planillas'], ['caja']]

/** Paga el neto de los trabajadores elegidos. Lleva clave de idempotencia: un reintento no paga dos veces. */
export function usePagarPlanilla(id, { exito, alExito } = {}) {
  return useMutacion({
    mutationFn: ({ datos, llave }) => api.post(`${URL}/${id}/pagar/`, datos, { headers: { 'Idempotency-Key': llave }, timeout: 60_000 }).then((r) => r.data),
    invalidar: INVALIDAR_PAGO,
    exito,
    alExito,
    avisarError: false,
  })
}

export function useAnularPago(id, { exito, alExito } = {}) {
  return useMutacion({
    mutationFn: ({ pago, motivo }) => api.post(`${URL}/${id}/pagos/${pago}/anular/`, { motivo }).then((r) => r.data),
    invalidar: INVALIDAR_PAGO,
    exito,
    alExito,
    avisarError: false,
  })
}
