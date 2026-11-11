import ActaEntregaA4 from './components/ActaEntregaA4'
import ActaEntregaTicket from './components/ActaEntregaTicket'
import EtiquetaEquipo from './components/EtiquetaEquipo'
import HojaIngresoA4 from './components/HojaIngresoA4'
import HojaIngresoTicket from './components/HojaIngresoTicket'

/** Los formatos de impresión de una orden: hoja A4, ticket y etiqueta del equipo. */
export const especificacionIngreso = (o) => ({
  tipo: 'ingreso-servicio',
  titulo: `Hoja de ingreso ${o.codigo}`,
  subtitulo: o.cliente_nombre,
  formatos: { A4: <HojaIngresoA4 orden={o} />, TICKET: <HojaIngresoTicket orden={o} />, ETIQUETA: <EtiquetaEquipo orden={o} /> },
})

/** El acta de entrega de una orden ya entregada: hoja A4 y ticket. */
export const especificacionActa = (o) => ({
  tipo: 'acta-entrega',
  titulo: `Acta de entrega ${o.codigo}`,
  subtitulo: o.cliente_nombre,
  formatos: { A4: <ActaEntregaA4 orden={o} />, TICKET: <ActaEntregaTicket orden={o} /> },
})
