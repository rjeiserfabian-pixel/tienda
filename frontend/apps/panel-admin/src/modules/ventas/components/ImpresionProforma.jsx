import ImpresionDesdeLista from './ImpresionDesdeLista'
import ProformaImpresa from './ProformaImpresa'
import ProformaTicket from './ProformaTicket'

const especificacion = (p) => ({ tipo: 'proforma', titulo: `Proforma ${p.numero_completo}`, subtitulo: p.cliente_nombre, formatos: { A4: <ProformaImpresa proforma={p} />, TICKET: <ProformaTicket proforma={p} /> } })

/** Vista previa de impresión de una proforma del listado (A4 o ticket), sin abrir su ficha. */
export default function ImpresionProforma({ id }) {
  // La misma clave de la ficha (el id de la ruta es texto): si ya se vio, no se pide otra vez.
  return <ImpresionDesdeLista clave={['ventas', 'proforma', String(id)]} url={`/ventas/proformas/${id}/`} especificacion={especificacion} />
}
