import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import ReciboA4 from './ReciboA4'
import ReciboTicket from './ReciboCobranza'
import VistaPreviaImpresion from './VistaPreviaImpresion'

/** Trae el recibo de un cobro de cuotas y lo muestra para imprimirlo en ticket o en hoja A4. */
export default function ReciboVistaPrevia({ id, onCerrar }) {
  const notificar = useNotificar()
  const consulta = useQuery({
    queryKey: ['ventas', 'recibo', id],
    queryFn: ({ signal }) => api.get(`/ventas/recibos/${id}/`, { signal }).then((r) => r.data),
    staleTime: 0,
    retry: 0,
  })
  useEffect(() => {
    if (!consulta.isError) return
    notificar('error', mensajeDeError(consulta.error))
    onCerrar()
  }, [consulta.isError, consulta.error, notificar, onCerrar])

  const r = consulta.data
  if (!r) return null
  return <VistaPreviaImpresion tipo="recibo" titulo={`Recibo ${r.numero_completo}`} subtitulo={`${r.cliente.nombre} · ${r.comprobante.numero_completo}`} inicial="TICKET" formatos={{ TICKET: <ReciboTicket datos={r} />, A4: <ReciboA4 datos={r} /> }} onCerrar={onCerrar} />
}
