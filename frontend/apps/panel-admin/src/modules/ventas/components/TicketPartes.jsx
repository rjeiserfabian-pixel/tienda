import { useQuery } from '@tanstack/react-query'
import QRCode from 'qrcode'
import { useEffect } from 'react'
import { api } from '../../../core/api/client'

const SIN_AVISO = () => {}

const comoDataUrl = (blob) =>
  new Promise((resolver, rechazar) => {
    const lector = new FileReader()
    lector.onload = () => resolver(lector.result)
    lector.onerror = () => rechazar(lector.error)
    lector.readAsDataURL(blob)
  })

/** El logo de la empresa (solo lo entrega el servidor con sesión). `onListo` avisa cuando ya cargó o falló. */
export function Logo({ empresa, onListo = SIN_AVISO }) {
  const consulta = useQuery({
    queryKey: ['imagen', `/organizacion/empresas/${empresa}/logo/`],
    queryFn: ({ signal }) => api.get(`/organizacion/empresas/${empresa}/logo/`, { responseType: 'blob', signal }).then((r) => comoDataUrl(r.data)),
    staleTime: 30 * 60_000,
    retry: 0,
  })
  useEffect(() => {
    if (consulta.isSuccess || consulta.isError) onListo()
  }, [consulta.isSuccess, consulta.isError, onListo])
  return consulta.data ? <img className="ticket-logo" src={consulta.data} alt="" onLoad={onListo} /> : null
}

/** El QR del ticket: al escanearlo muestra la dirección, el RUC y el celular de quien vende. `onListo` avisa cuando ya se dibujó. */
export function QrEmisor({ texto, onListo = SIN_AVISO }) {
  const consulta = useQuery({
    queryKey: ['qr-recibo', texto],
    queryFn: () => QRCode.toDataURL(texto, { margin: 1, width: 220, errorCorrectionLevel: 'M' }),
    staleTime: Infinity,
    retry: 0,
  })
  useEffect(() => {
    if (consulta.isSuccess || consulta.isError) onListo()
  }, [consulta.isSuccess, consulta.isError, onListo])
  return consulta.data ? <img className="ticket-qr" src={consulta.data} alt="QR con la dirección, el RUC y el celular" onLoad={onListo} /> : null
}

/** La cabecera de los tickets de documentos internos: el logo (si la empresa lo tiene), quién emite, su RUC y el título con el número. */
export function EmisorTicket({ emisor, titulo, numero }) {
  return (
    <header>
      {emisor.tiene_logo && <Logo empresa={emisor.empresa} />}
      <strong>{emisor.nombre}</strong>
      <span>RUC: {emisor.ruc}</span>
      {emisor.direccion && <span>{emisor.direccion}</span>}
      {emisor.telefono && <span>TELÉFONOS: {emisor.telefono}</span>}
      <b>
        {titulo} {numero}
      </b>
    </header>
  )
}
