import { useQuery } from '@tanstack/react-query'
import QRCode from 'qrcode'
import { useEffect } from 'react'

const SIN_AVISO = () => {}

/** El QR del certificado: lleva a la consulta pública de la garantía. `onListo` avisa cuando ya se dibujó (o falló). */
export default function QrGarantia({ url, clase = 'ingreso-qr', onListo = SIN_AVISO }) {
  const consulta = useQuery({
    queryKey: ['qr-garantia', url],
    queryFn: () => QRCode.toDataURL(url, { margin: 1, width: 240, errorCorrectionLevel: 'M' }),
    staleTime: Infinity,
    retry: 0,
    enabled: Boolean(url),
  })
  useEffect(() => {
    if (consulta.isSuccess || consulta.isError) onListo()
  }, [consulta.isSuccess, consulta.isError, onListo])
  return consulta.data ? <img className={clase} src={consulta.data} alt="QR para consultar la garantía" onLoad={onListo} /> : null
}
