import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { useImpresionDocumento } from '../hooks/useImpresionDocumento'

/**
 * Abre la vista previa de impresión de un documento desde un listado, sin abrir su detalle: trae el
 * documento (`url`) y muestra la vista previa en cuanto llega. `especificacion(datos)` arma lo que se
 * muestra (ver `useImpresionDocumento`). No dibuja nada más; para abrirla otra vez se vuelve a montar
 * con otra `key`.
 */
export default function ImpresionDesdeLista({ clave, url, especificacion }) {
  const notificar = useNotificar()
  const consulta = useQuery({
    queryKey: clave,
    queryFn: ({ signal }) => api.get(url, { signal }).then((r) => r.data),
  })
  const datos = consulta.data
  const { imprimir, portal } = useImpresionDocumento(datos ? especificacion(datos) : null)
  useEffect(() => {
    if (datos) imprimir()
  }, [datos, imprimir])
  useEffect(() => {
    if (consulta.isError) notificar('error', mensajeDeError(consulta.error))
  }, [consulta.isError, consulta.error, notificar])
  return portal
}
