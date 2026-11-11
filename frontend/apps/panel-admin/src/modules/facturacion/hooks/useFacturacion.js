import { useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'

/** Configuración de la facturación electrónica de una empresa (las claves nunca llegan). */
export function useConfiguracionFe(empresaId) {
  return useQuery({
    queryKey: ['facturacion', 'configuracion', empresaId],
    queryFn: ({ signal }) => api.get('/facturacion/configuracion/', { params: { empresa: empresaId }, signal }).then((r) => r.data),
    enabled: Boolean(empresaId),
  })
}

/** El JSON que se enviaría a la API, con las claves ocultas. */
export function useVistaPreviaFe(origen, id) {
  return useQuery({
    queryKey: ['facturacion', 'vista-previa', origen, id],
    queryFn: ({ signal }) => api.get('/facturacion/vista-previa/', { params: { origen, id }, signal }).then((r) => r.data),
    staleTime: 0,
    gcTime: 0, // no se guarda en la memoria del navegador más de lo necesario
    retry: false,
  })
}
