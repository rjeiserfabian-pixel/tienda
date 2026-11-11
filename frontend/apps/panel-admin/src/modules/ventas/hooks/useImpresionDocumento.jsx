import { useCallback, useState } from 'react'
import { createPortal } from 'react-dom'
import VistaPreviaImpresion from '../components/VistaPreviaImpresion'

/**
 * Muestra un documento (una proforma, una guía, una nota de crédito) para imprimirlo en hoja A4 o en
 * ticket. Recibe lo que hay que mostrar, o `null` si todavía no hay datos:
 *
 *   { tipo, titulo, subtitulo, inicial, formatos: { A4: <Documento />, TICKET: <DocumentoTicket /> } }
 *
 * `imprimir()` abre la vista previa; `portal` debe ir en el JSX de la página.
 */
export function useImpresionDocumento(documento) {
  const [abierta, setAbierta] = useState(false)
  const imprimir = useCallback(() => setAbierta(true), [])
  const cerrar = useCallback(() => setAbierta(false), [])
  const portal = abierta && documento ? createPortal(<VistaPreviaImpresion {...documento} onCerrar={cerrar} />, document.body) : null
  return { imprimir, portal }
}
