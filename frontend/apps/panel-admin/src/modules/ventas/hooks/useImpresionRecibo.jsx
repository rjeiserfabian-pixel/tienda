import { useCallback, useState } from 'react'
import { createPortal } from 'react-dom'
import ReciboVistaPrevia from '../components/ReciboVistaPrevia'

/**
 * Muestra el recibo de un cobro de cuotas para imprimirlo (ticket o A4). `imprimir(reciboId)` abre la
 * vista previa; `portal` debe ir en el JSX de la página.
 */
export function useImpresionRecibo() {
  const [id, setId] = useState(null)
  const cerrar = useCallback(() => setId(null), [])
  const portal = id ? createPortal(<ReciboVistaPrevia key={id} id={id} onCerrar={cerrar} />, document.body) : null
  return { imprimir: setId, portal }
}
