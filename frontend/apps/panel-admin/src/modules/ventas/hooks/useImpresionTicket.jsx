import { useCallback, useState } from 'react'
import { createPortal } from 'react-dom'
import ComprobanteA4 from '../components/ComprobanteA4'
import Ticket from '../components/Ticket'
import VistaPreviaImpresion from '../components/VistaPreviaImpresion'

/**
 * Muestra un comprobante de una venta para imprimirlo en ticket de 80 mm o en hoja A4.
 * `imprimir(comprobante)` abre la vista previa; `portal` debe ir en el JSX de la página.
 */
export function useImpresionTicket(venta) {
  const [actual, setActual] = useState(null)
  const cerrar = useCallback(() => setActual(null), [])
  const portal =
    actual && venta
      ? createPortal(
          <VistaPreviaImpresion
            tipo="comprobante"
            titulo={`${actual.tipo_nombre} ${actual.numero_completo}`}
            subtitulo={`${actual.empresa_nombre} · ${venta.cliente_nombre}`}
            inicial="TICKET"
            formatos={{ TICKET: <Ticket venta={venta} comprobante={actual} />, A4: <ComprobanteA4 venta={venta} comprobante={actual} /> }}
            onCerrar={cerrar}
          />,
          document.body,
        )
      : null
  return { imprimir: setActual, portal }
}
