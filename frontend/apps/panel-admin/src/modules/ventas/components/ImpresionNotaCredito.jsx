import ImpresionDesdeLista from './ImpresionDesdeLista'
import NotaCreditoImpresa from './NotaCreditoImpresa'
import NotaCreditoTicket from './NotaCreditoTicket'

const especificacion = (n) => ({ tipo: 'nota-credito', titulo: `Nota de crédito ${n.numero_completo}`, subtitulo: `Sobre ${n.comprobante_numero} · ${n.cliente_nombre}`, formatos: { A4: <NotaCreditoImpresa nota={n} />, TICKET: <NotaCreditoTicket nota={n} /> } })

/** Vista previa de impresión de una nota de crédito del listado (A4 o ticket), sin abrir su detalle. */
export default function ImpresionNotaCredito({ id }) {
  return <ImpresionDesdeLista clave={['ventas', 'nota-credito', id]} url={`/ventas/notas-credito/${id}/`} especificacion={especificacion} />
}
