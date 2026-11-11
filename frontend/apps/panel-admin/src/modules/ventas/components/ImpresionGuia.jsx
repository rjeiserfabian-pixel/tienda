import GuiaImpresa from './GuiaImpresa'
import GuiaTicket from './GuiaTicket'
import ImpresionDesdeLista from './ImpresionDesdeLista'

const especificacion = (g) => ({ tipo: 'guia', titulo: `Guía ${g.numero_completo}`, subtitulo: `De ${g.comprobante_numero} · ${g.destinatario_nombre}`, formatos: { A4: <GuiaImpresa guia={g} />, TICKET: <GuiaTicket guia={g} /> } })

/** Vista previa de impresión de una guía de remisión del listado (A4 o ticket), sin abrir su detalle. */
export default function ImpresionGuia({ id }) {
  // La misma clave del detalle: si ya se vio, no se pide otra vez.
  return <ImpresionDesdeLista clave={['ventas', 'guia', id]} url={`/ventas/guias-remision/${id}/`} especificacion={especificacion} />
}
