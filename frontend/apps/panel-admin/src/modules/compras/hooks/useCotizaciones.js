import { useQueries, useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { api } from '../../../core/api/client'
import { borradorDesdeCotizacion } from '../cotizaciones'

/** Clave de consulta de una cotización: la invalida cualquier acción de `['compras']`. */
export const claveCotizacion = (id) => ['compras', 'cotizaciones', 'detalle', String(id)]

/** La cotización completa (cabecera, productos, proveedores y comparativo). */
export function useCotizacion(id) {
  return useQuery({
    queryKey: claveCotizacion(id),
    queryFn: ({ signal }) => api.get(`/compras/cotizaciones/${id}/`, { signal }).then((r) => r.data),
    enabled: Boolean(id),
  })
}

const porId = (resultados) => ({
  listo: resultados.every((r) => r.isSuccess),
  error: resultados.find((r) => r.isError) ?? null,
  datos: Object.fromEntries(resultados.filter((r) => r.data).map((r) => [r.data.id, r.data])),
})

/** Lo que necesita `EstadoConsulta`: cargando, error (con su reintento) o listo. */
function estadoDe(cotizacion, borrador, productos, proveedores) {
  const fallo = cotizacion.isError ? cotizacion : (productos.error ?? proveedores.error)
  return {
    isLoading: !fallo && !borrador,
    isError: Boolean(fallo),
    error: fallo?.error,
    refetch: () => fallo?.refetch?.(),
  }
}

/** La cotización que se va a editar, con los productos y proveedores completos para llenar el formulario. */
export function useCotizacionParaEditar(id) {
  const cotizacion = useQuery({
    queryKey: [...claveCotizacion(id), 'edicion'],
    queryFn: ({ signal }) => api.get(`/compras/cotizaciones/${id}/`, { signal }).then((r) => r.data),
    enabled: Boolean(id),
    staleTime: 0,
  })
  const productoIds = useMemo(() => [...new Set((cotizacion.data?.lineas ?? []).map((l) => l.producto))], [cotizacion.data])
  const proveedorIds = useMemo(() => [...new Set((cotizacion.data?.proveedores ?? []).map((p) => p.proveedor))], [cotizacion.data])
  const productos = useQueries({
    queries: productoIds.map((pid) => ({
      queryKey: ['productos', 'detalle', pid],
      queryFn: ({ signal }) => api.get(`/mantenimiento/productos/${pid}/`, { signal }).then((r) => r.data),
      staleTime: 60_000,
    })),
    combine: porId,
  })
  const proveedores = useQueries({
    queries: proveedorIds.map((pid) => ({
      queryKey: ['proveedores', 'detalle', pid],
      queryFn: ({ signal }) => api.get(`/mantenimiento/proveedores/${pid}/`, { signal }).then((r) => r.data),
      staleTime: 60_000,
    })),
    combine: porId,
  })
  const listo = Boolean(cotizacion.data) && productos.listo && proveedores.listo
  const borrador = useMemo(() => (listo ? borradorDesdeCotizacion(cotizacion.data, productos.datos, proveedores.datos) : null), [listo, cotizacion.data, productos.datos, proveedores.datos])
  return { cotizacion: cotizacion.data, borrador, consulta: estadoDe(cotizacion, borrador, productos, proveedores) }
}
