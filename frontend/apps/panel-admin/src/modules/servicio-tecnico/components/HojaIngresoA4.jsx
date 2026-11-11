import { Logo } from '../../ventas/components/TicketPartes'
import { fechaCorta } from '../../almacen/inventario'
import { CONDICIONES_INGRESO, fechaHora } from '../servicio'
import QrOrden from './QrOrden'
import '../../ventas/ventas.css'
import '../servicio-tecnico.css'

const equipoTexto = (e) => [e.tipo, e.marca, e.modelo].filter(Boolean).join(' ')

/** La hoja de ingreso en A4: lo que el taller recibe, en qué estado y bajo qué condiciones. Lleva dos firmas. */
export default function HojaIngresoA4({ orden: o }) {
  const e = o.equipo_datos
  const fallas = o.revisiones.filter((r) => r.resultado === 'FALLA')
  return (
    <article className="documento" aria-label={`Hoja de ingreso ${o.codigo}`}>
      <header>
        <div>
          {o.emisor.tiene_logo && <Logo empresa={o.emisor.empresa} />}
          <h1>{o.emisor.nombre}</h1>
          <span>RUC {o.emisor.ruc}</span>
          {o.emisor.direccion && <span>{o.emisor.direccion}</span>}
          {(o.emisor.telefono || o.emisor.correo) && <span>{[o.emisor.telefono, o.emisor.correo].filter(Boolean).join(' · ')}</span>}
        </div>
        <div className="documento-numero">
          <h1>ORDEN DE SERVICIO</h1>
          <strong>N° {o.codigo}</strong>
          <span>Ingreso: {fechaHora(o.fecha_ingreso)}</span>
          {o.fecha_promesa && <span>Fecha prometida: {fechaCorta(o.fecha_promesa)}</span>}
        </div>
      </header>
      <div className="ingreso-cuerpo">
        <p>
          <strong>Cliente:</strong> {o.cliente_nombre} · {o.cliente_documento}
          {o.cliente_telefono ? ` · Tel. ${o.cliente_telefono}` : ''}
          {o.cliente_direccion && (
            <>
              <br />
              <strong>Dirección:</strong> {o.cliente_direccion}
            </>
          )}
          <br />
          <strong>Recibido por:</strong> {o.recibido_por || '—'}
          {o.tecnico_nombre ? ` · Técnico: ${o.tecnico_nombre}` : ''}
        </p>
        <p>
          <strong>Equipo:</strong> {equipoTexto(e)}
          {e.numero_serie ? ` · Serie ${e.numero_serie}` : ''}
          {e.color ? ` · Color ${e.color}` : ''}
          {e.descripcion && (
            <>
              <br />
              <strong>Características:</strong> {e.descripcion}
            </>
          )}
        </p>
        <p>
          <strong>Falla que reporta el cliente:</strong> {o.falla_reportada}
          <br />
          <strong>Estado físico al recibirlo:</strong> {o.estado_fisico || 'Sin observaciones'}
          <br />
          <strong>Clave o patrón:</strong> {o.tiene_clave ? 'Entregada por el cliente (registrada en el sistema)' : 'No entregó'}
        </p>
        <p>
          <strong>Accesorios que deja:</strong>{' '}
          {o.accesorios.length === 0 ? 'Ninguno' : o.accesorios.map((a) => `${a.cantidad} ${a.nombre}${a.detalle ? ` (${a.detalle})` : ''}`).join(' · ')}
        </p>
        {o.revisiones.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Revisión al recibirlo</th>
                <th>Resultado</th>
                <th>Observación</th>
              </tr>
            </thead>
            <tbody>
              {o.revisiones.map((r) => (
                <tr key={r.id}>
                  <td>{r.nombre}</td>
                  <td>{r.resultado_nombre}</td>
                  <td>{r.observacion}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {fallas.length > 0 && <p className="celda-suave">Con falla al recibirlo: {fallas.map((r) => r.nombre).join(', ')}.</p>}
      </div>
      <footer>
        <div className="ingreso-pie">
          <ul className="ingreso-condiciones">
            {CONDICIONES_INGRESO.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          <span className="ingreso-qr-bloque">
            <QrOrden orden={o} publico />
            <small>Escanea para ver el estado de tu equipo</small>
          </span>
        </div>
        <div className="ingreso-firmas">
          <span>Firma del cliente</span>
          <span>Recepción — {o.emisor.nombre}</span>
        </div>
      </footer>
    </article>
  )
}
