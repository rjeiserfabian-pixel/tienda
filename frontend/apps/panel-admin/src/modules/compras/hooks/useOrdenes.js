import { keepPreviousData, useQueries, useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { borradorDesdeOrden, borradorParaRecibir } from '../ordenes'

/**
 * Vista previa de la orden: el servidor calcula totales e IGV sin guardar nada y dice si pediría
 * aprobación. Se pide con 450 ms de retraso para no calcular en cada tecla.
 */
export function useCalculoOrden(cuerpo, activo) {
  const texto = useDebounce(JSON.stringify(cuerpo), 450)
  const esperando = texto !== JSON.stringify(cuerpo)
  const consulta = useQuery({
    queryKey: ['compras', 'ordenes', 'calcular', texto],
    queryFn: ({ signal }) => api.post('/compras/ordenes/calcular/', JSON.parse(texto), { signal }).then((r) => r.data),
    enabled: activo,
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 30_000,
  })
  return {
    datos: activo ? consulta.data : undefined,
    calculando: activo && (esperando || consulta.isFetching),
    error: activo && consulta.isError && !esperando ? mensajeDeError(consulta.error) : '',
  }
}

const combinarProductos = (resultados) => ({
  listo: resultados.every((r) => r.isSuccess),
  error: resultados.find((r) => r.isError) ?? null,
  porId: Object.fromEntries(resultados.filter((r) => r.data).map((r) => [r.data.id, r.data])),
})

/** Los productos (con sus presentaciones) y el proveedor de una orden, para armar un borrador. */
function useDatosDeOrden(productoIds, proveedorId) {
  const unicos = useMemo(() => [...new Set(productoIds)], [productoIds])
  const productos = useQueries({
    queries: unicos.map((id) => ({
      queryKey: ['productos', 'detalle', id],
      queryFn: ({ signal }) => api.get(`/mantenimiento/productos/${id}/`, { signal }).then((r) => r.data),
      staleTime: 60_000,
    })),
    combine: combinarProductos,
  })
  const proveedor = useQuery({
    queryKey: ['proveedores', 'detalle', proveedorId],
    queryFn: ({ signal }) => api.get(`/mantenimiento/proveedores/${proveedorId}/`, { signal }).then((r) => r.data),
    enabled: Boolean(proveedorId),
    staleTime: 60_000,
  })
  return {
    listo: Boolean(proveedorId) && proveedor.isSuccess && productos.listo,
    error: productos.error ?? (proveedor.isError ? proveedor : null),
    productos: productos.porId,
    proveedor: proveedor.data,
  }
}

/** Lo que necesita `EstadoConsulta`: cargando, error (con su reintento) o listo. */
function estadoDe(orden, borrador, datos) {
  const fallo = orden.isError ? orden : datos.error
  return {
    isLoading: !fallo && !borrador,
    isError: Boolean(fallo),
    error: fallo?.error,
    refetch: () => fallo?.refetch?.(),
  }
}

/** La orden que se va a editar, con lo necesario para llenar el formulario. */
export function useOrdenParaEditar(id) {
  const orden = useQuery({
    queryKey: ['compras', 'ordenes', 'detalle', String(id)],
    queryFn: ({ signal }) => api.get(`/compras/ordenes/${id}/`, { signal }).then((r) => r.data),
    enabled: Boolean(id),
    staleTime: 0,
  })
  const ids = useMemo(() => (orden.data?.lineas ?? []).map((l) => l.producto), [orden.data])
  const datos = useDatosDeOrden(ids, orden.data?.proveedor)
  const borrador = useMemo(() => (orden.data && datos.listo ? borradorDesdeOrden(orden.data, datos.productos, datos.proveedor) : null), [orden.data, datos.listo, datos.productos, datos.proveedor])
  return { orden: orden.data, borrador, consulta: estadoDe(orden, borrador, datos) }
}

/** Lo que falta recibir de una orden, convertido en el borrador de «Registrar compra». */
export function useRecepcionDeOrden(id) {
  const orden = useQuery({
    queryKey: ['compras', 'ordenes', 'por-recibir', String(id)],
    queryFn: ({ signal }) => api.get(`/compras/ordenes/${id}/por-recibir/`, { signal }).then((r) => r.data),
    enabled: Boolean(id),
    staleTime: 0,
  })
  const ids = useMemo(() => (orden.data?.lineas ?? []).map((l) => l.producto), [orden.data])
  const datos = useDatosDeOrden(ids, orden.data?.proveedor)
  const borrador = useMemo(() => (orden.data && datos.listo ? borradorParaRecibir(orden.data, datos.productos, datos.proveedor) : null), [orden.data, datos.listo, datos.productos, datos.proveedor])
  return { orden: orden.data, borrador, consulta: estadoDe(orden, borrador, datos) }
}
