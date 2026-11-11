import { fechaCorta } from '../../almacen/inventario'
import { Logo } from '../../ventas/components/TicketPartes'
import { CONDICIONES_GARANTIA, fechaHora } from '../servicio'
import '../../ventas/ventas.css'
import '../servicio-tecnico.css'

/** El acta de entrega en A4: qué se entrega, a quién, qué se hizo y qué garantía queda. Lleva dos firmas. */
export default function ActaEntregaA4({ orden: o }) {
  const e = o.equipo_datos
  const comprobantes = o.presupuesto?.venta?.comprobantes ?? []
  return (
    <article className="documento" aria-label={`Acta de entrega ${o.codigo}`}>
      <header>
        <div>
          {o.emisor.tiene_logo && <Logo empresa={o.emisor.empresa} />}
          <h1>{o.emisor.nombre}</h1>
          <span>RUC {o.emisor.ruc}</span>
          {o.emisor.direccion && <span>{o.emisor.direccion}</span>}
          {(o.emisor.telefono || o.emisor.correo) && <span>{[o.emisor.telefono, o.emisor.correo].filter(Boolean).join(' · ')}</span>}
        </div>
        <div className="documento-numero">
          <h1>ACTA DE ENTREGA</h1>
          <strong>Orden {o.codigo}</strong>
          <span>Ingreso: {fechaHora(o.fecha_ingreso)}</span>
          <span>Entrega: {fechaHora(o.fecha_entrega)}</span>
        </div>
      </header>
      <div className="ingreso-cuerpo">
        <p>
          <strong>Cliente:</strong> {o.cliente_nombre} · {o.cliente_documento}
          <br />
          <strong>Recoge:</strong> {o.recogio_nombre}
          {o.recogio_es_titular ? ' (titular)' : ` · DNI ${o.recogio_documento} (en nombre del titular)`}
        </p>
        <p>
          <strong>Equipo:</strong> {[e.tipo, e.marca, e.modelo].filter(Boolean).join(' ')}
          {e.numero_serie ? ` · Serie ${e.numero_serie}` : ''}
        </p>
        <p>
          <strong>Falla reportada:</strong> {o.falla_reportada}
          {o.diagnostico && (
            <>
              <br />
              <strong>Diagnóstico:</strong> {o.diagnostico}
            </>
          )}
          {o.trabajos_a_realizar && (
            <>
              <br />
              <strong>Trabajos realizados:</strong> {o.trabajos_a_realizar}
            </>
          )}
          {o.tipo_servicio_nombre && (
            <>
              <br />
              <strong>Servicio:</strong> {o.tipo_servicio_nombre}
            </>
          )}
        </p>
        <p>
          <strong>Accesorios que se devuelven:</strong> {o.accesorios.length === 0 ? 'Ninguno' : o.accesorios.map((a) => `${a.cantidad} ${a.nombre}`).join(' · ')}
        </p>
        {comprobantes.length > 0 && (
          <p>
            <strong>Comprobantes:</strong> {comprobantes.map((c) => `${c.tipo_nombre} ${c.numero_completo} (${c.empresa_nombre})`).join(' · ')}
          </p>
        )}
        {o.es_garantia && (
          <p>
            <strong>Servicio en garantía</strong> de la orden {o.reingreso_de_codigo}: sin costo para el cliente.
          </p>
        )}
        <p>
          <strong>Garantía:</strong> {o.garantia.dias > 0 ? `${o.garantia.dias} días, hasta el ${fechaCorta(o.garantia.hasta)}` : 'Este servicio no tiene garantía.'}
        </p>
      </div>
      <footer>
        {o.garantia.dias > 0 && (
          <ul className="ingreso-condiciones">
            {CONDICIONES_GARANTIA.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        )}
        <p className="celda-suave">Recibí el equipo y sus accesorios en conformidad.</p>
        <div className="ingreso-firmas">
          <span>Firma de quien recoge</span>
          <span>Entrega — {o.emisor.nombre}</span>
        </div>
      </footer>
    </article>
  )
}
