import { useQuery } from '@tanstack/react-query'
import QRCode from 'qrcode'
import { useEffect } from 'react'
import { direccionDeOrden } from '../servicio'

const SIN_AVISO = () => {}

/** El QR de la orden. `onListo` avisa cuando ya se dibujó (o falló), para no imprimir una hoja sin él. */
export default function QrOrden({ orden, clase = 'ingreso-qr', publico = false, onListo = SIN_AVISO }) {
  const texto = publico && orden.url_publica ? orden.url_publica : direccionDeOrden(orden.id)
  const consulta = useQuery({
    queryKey: ['qr-orden', texto],
    queryFn: () => QRCode.toDataURL(texto, { margin: 1, width: 240, errorCorrectionLevel: 'M' }),
    staleTime: Infinity,
    retry: 0,
  })
  useEffect(() => {
    if (consulta.isSuccess || consulta.isError) onListo()
  }, [consulta.isSuccess, consulta.isError, onListo])
  return consulta.data ? <img className={clase} src={consulta.data} alt={`QR de la orden ${orden.codigo}`} onLoad={onListo} /> : null
}
