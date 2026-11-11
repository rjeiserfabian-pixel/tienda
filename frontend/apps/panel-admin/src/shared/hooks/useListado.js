import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from '../../core/api/client'

/** Quita parámetros vacíos para no enviar `?q=&activo=` al backend. */
export const sinVacios = (parametros) =>
  Object.fromEntries(
    Object.entries(parametros).filter(([, v]) => v !== '' && v !== null && v !== undefined),
  )

/**
 * Listado paginado del servidor. Conserva la página anterior mientras llega la nueva
 * (la tabla no parpadea) y cancela la petición si el componente se desmonta.
 */
export function useListado(clave, url, parametros, opciones = {}) {
  const limpios = sinVacios(parametros)
  return useQuery({
    queryKey: [...clave, 'lista', limpios],
    queryFn: ({ signal }) => api.get(url, { params: limpios, signal }).then((r) => r.data),
    placeholderData: keepPreviousData,
    ...opciones, // p. ej. `enabled: false` mientras falta un dato para consultar
  })
}
