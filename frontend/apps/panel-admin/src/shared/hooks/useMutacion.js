import { useMutation, useQueryClient } from '@tanstack/react-query'
import { mensajeDeError } from '../../core/api/client'
import { useNotificar } from '../contexts/NotificacionesContext'

/**
 * Mutación con aviso de éxito/error e invalidación de las consultas afectadas.
 * `invalidar` es una lista de claves de consulta (`['usuarios']` invalida todo ese grupo).
 * `exito` puede ser un texto o una función que lo arma con la respuesta.
 * El error por campo lo maneja cada formulario; aquí solo se avisa si `avisarError` es true.
 */
export function useMutacion({ mutationFn, invalidar = [], exito, alExito, avisarError = true }) {
  const queryClient = useQueryClient()
  const notificar = useNotificar()

  return useMutation({
    mutationFn,
    onSuccess: async (datos, variables) => {
      await Promise.all(invalidar.map((clave) => queryClient.invalidateQueries({ queryKey: clave })))
      if (exito) notificar('exito', typeof exito === 'function' ? exito(datos) : exito)
      alExito?.(datos, variables)
    },
    onError: (error) => {
      if (avisarError) notificar('error', mensajeDeError(error))
    },
  })
}
