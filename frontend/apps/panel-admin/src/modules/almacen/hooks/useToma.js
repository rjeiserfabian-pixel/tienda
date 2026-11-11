import { useQuery } from '@tanstack/react-query'
import { useCallback, useRef, useState } from 'react'
import { api, codigoDeError, mensajeDeError } from '../../../core/api/client'
import { useMutacion } from '../../../shared/hooks/useMutacion'

const URL = '/inventario/tomas'
// Todas las consultas de una toma cuelgan de ['tomas']: invalidar esa clave refresca todo.
export const claveToma = (id) => ['tomas', 'ficha', id]

/** Ficha de una toma (estado, alcance, umbrales, fechas). */
export function useToma(id) {
  return useQuery({
    queryKey: claveToma(id),
    queryFn: ({ signal }) => api.get(`${URL}/${id}/`, { signal }).then((r) => r.data),
  })
}

/** Avance de la toma: contados, por contar, por recontar, por anotar y avance por categoría. */
export function useAvanceToma(id, { enabled = true } = {}) {
  return useQuery({
    queryKey: ['tomas', 'avance', id],
    queryFn: ({ signal }) => api.get(`${URL}/${id}/avance/`, { signal }).then((r) => r.data),
    enabled,
    refetchInterval: 20_000, // otras personas también cuentan: el avance se mantiene al día
  })
}

/** Turnos de trabajo de la toma. */
export function useTurnosToma(id, { enabled = true } = {}) {
  return useQuery({
    queryKey: ['tomas', 'turnos', id],
    queryFn: ({ signal }) => api.get(`${URL}/${id}/turnos/`, { signal }).then((r) => r.data),
    enabled,
  })
}

/** Una acción de la toma (abrir, reconteo, cerrar, anular…): POST a `/tomas/:id/<accion>/`. */
export function useAccionToma(id, accion, { exito, alExito } = {}) {
  return useMutacion({
    mutationFn: (cuerpo) => api.post(`${URL}/${id}/${accion}/`, cuerpo ?? {}, { timeout: 60_000 }).then((r) => r.data),
    invalidar: [['tomas'], ['stock'], ['movimientos'], ['kardex']],
    exito,
    alExito,
    avisarError: false,
  })
}

const nuevaClave = () =>
  globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`

/**
 * Registra conteos de la toma. Cada conteo viaja con una clave de idempotencia que se CONSERVA
 * mientras el contenido sea el mismo y no haya terminado bien: si la red falla y la persona
 * reintenta, el servidor no lo cuenta dos veces (un segundo conteo borraría la marca de reconteo).
 *
 * Un 0 de un producto con mucho stock pide confirmación: `cero` trae el aviso del servidor y
 * `confirmarCero()` repite el conteo confirmado.
 */
export function useRegistroConteo(tomaId) {
  const claves = useRef(new Map())
  const [cero, setCero] = useState(null)

  const mutacion = useMutacion({
    mutationFn: (cuerpo) => {
      const huella = JSON.stringify(cuerpo)
      if (!claves.current.has(huella)) claves.current.set(huella, nuevaClave())
      return api
        .post(`${URL}/${tomaId}/contar/`, cuerpo, { headers: { 'Idempotency-Key': claves.current.get(huella) }, timeout: 30_000 })
        .then((r) => {
          claves.current.delete(huella)
          return r.data
        })
    },
    invalidar: [['tomas']],
    avisarError: false,
  })
  const { mutateAsync } = mutacion

  /** `alExito(detalle)` y `alError(mensaje)` son opcionales. Cada llamada recibe su propia respuesta. */
  const registrar = useCallback(
    (cuerpo, { alExito, alError } = {}) => {
      mutateAsync(cuerpo)
        .then((detalle) => alExito?.(detalle))
        .catch((error) => {
          if (codigoDeError(error) === 'conteo_requiere_confirmacion') {
            setCero({ cuerpo, mensaje: mensajeDeError(error), alExito, alError })
          } else {
            alError?.(mensajeDeError(error))
          }
        })
    },
    [mutateAsync],
  )

  const confirmarCero = () => {
    if (!cero) return
    const { cuerpo, alExito, alError } = cero
    setCero(null)
    registrar({ ...cuerpo, confirmar_cero: true }, { alExito, alError })
  }
  const cancelarCero = () => {
    cero?.alError?.(null) // null = la persona no confirmó: quien llamó libera su botón sin mostrar error
    setCero(null)
  }

  return { registrar, pendiente: mutacion.isPending, cero, confirmarCero, cancelarCero }
}

/** Pone o cambia la nota de un producto ya contado (sin volver a contarlo). */
export function useNotaToma(tomaId) {
  const mutacion = useMutacion({
    mutationFn: (cuerpo) => api.post(`${URL}/${tomaId}/nota/`, cuerpo).then((r) => r.data),
    invalidar: [['tomas']],
    avisarError: false,
  })
  const { mutateAsync } = mutacion

  /** `alExito()` y `alError(mensaje)` son opcionales. */
  const guardarNota = useCallback(
    (cuerpo, { alExito, alError } = {}) => {
      mutateAsync(cuerpo)
        .then(() => alExito?.())
        .catch((error) => alError?.(mensajeDeError(error)))
    },
    [mutateAsync],
  )
  return { guardarNota, pendiente: mutacion.isPending }
}

/**
 * Todos los productos con serie o IMEI que tienen diferencia (para pedir qué series entran o salen).
 * Recorre las páginas del servidor: no se pierde ninguno aunque sean muchos.
 */
export function useAjustesConSerie(id, { enabled = true } = {}) {
  return useQuery({
    queryKey: ['tomas', 'ajustes-serie', id],
    enabled,
    queryFn: async ({ signal }) => {
      const filas = []
      for (let pagina = 1; pagina <= 20; pagina += 1) {
        const { data } = await api.get(`${URL}/${id}/ajustes/`, { params: { lleva_serie: 1, page: pagina, page_size: 100 }, signal })
        filas.push(...data.results)
        if (!data.next) break
      }
      return filas
    },
  })
}

/** Las series de un producto que hay ahora en el almacén (para elegir cuáles salen en un faltante). */
export function useSeriesEnStock({ empresa, almacen, producto, enabled }) {
  return useQuery({
    queryKey: ['tomas', 'series-en-stock', empresa, almacen, producto],
    enabled,
    queryFn: ({ signal }) =>
      api.get('/inventario/series/', { params: { empresa, almacen, producto, estado: 'EN_STOCK', page_size: 100 }, signal }).then((r) => r.data),
  })
}
