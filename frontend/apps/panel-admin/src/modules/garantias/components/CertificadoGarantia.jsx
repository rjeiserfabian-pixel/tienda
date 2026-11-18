import { fechaCorta } from '../../almacen/inventario'
import { EmisorTicket, Logo } from '../../ventas/components/TicketPartes'
import QrGarantia from './QrGarantia'
import '../../ventas/ventas.css'
import '../../servicio-tecnico/servicio-tecnico.css'

const unidades = (g) => (!g.numero_serie && Number(g.cantidad) !== 1 ? ` (${Number(g.cantidad)} unidades)` : '')

/** El certificado de garantía en A4: qué se vendió, a quién, hasta cuándo vale y bajo qué condiciones. */
export function CertificadoGarantiaA4({ garantia: g }) {
  const e = g.emisor
  return (
    <article className="documento" aria-label={`Certificado de garantía ${g.comprobante_numero}`}>
      <header>
        <div>
          {e.tiene_logo && <Logo empresa={e.empresa} />}
          <h1>{e.nombre}</h1>
          <span>RUC {e.ruc}</span>
          {e.direccion && <span>{e.direccion}</span>}
          {(e.telefono || e.correo) && <span>{[e.telefono, e.correo].filter(Boolean).join(' · ')}</span>}
        </div>
        <div className="documento-numero">
          <h1>CERTIFICADO DE GARANTÍA</h1>
          <strong>{g.comprobante_numero}</strong>
          <span>Venta: {fechaCorta(g.fecha_inicio)}</span>
        </div>
      </header>
      <div className="ingreso-cuerpo">
        <p>
          <strong>Cliente:</strong> {g.cliente_nombre || '—'}
          {g.cliente_documento ? ` · ${g.cliente_documento}` : ''}
        </p>
        <p>
          <strong>Producto:</strong> {g.producto_nombre}
          {unidades(g)}
          {g.numero_serie && (
            <>
              <br />
              <strong>Serie / IMEI:</strong> {g.numero_serie}
            </>
          )}
        </p>
        <p>
          <strong>Garantía:</strong> {g.meses} {g.meses === 1 ? 'mes' : 'meses'}, desde el {fechaCorta(g.fecha_inicio)} hasta el <strong>{fechaCorta(g.vence_el)}</strong>
        </p>
      </div>
      <footer>
        <div className="ingreso-pie">
          <ul className="ingreso-condiciones">
            {g.condiciones.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          <span className="ingreso-qr-bloque">
            <QrGarantia url={g.url_publica} />
            <small>Escanea para consultar tu garantía</small>
          </span>
        </div>
        <div className="ingreso-firmas">
          <span>Firma del cliente</span>
          <span>{e.nombre}</span>
        </div>
      </footer>
    </article>
  )
}

/** El certificado en ticket de 80 mm. */
export function CertificadoGarantiaTicket({ garantia: g }) {
  return (
    <article className="ticket" aria-label={`Certificado de garantía ${g.comprobante_numero}`}>
      <EmisorTicket emisor={g.emisor} titulo="CERTIFICADO DE GARANTÍA" numero={g.comprobante_numero} />
      <p>
        <b>CLIENTE:</b> {g.cliente_nombre || '—'}
        {g.cliente_documento && (
          <>
            <br />
            {g.cliente_documento}
          </>
        )}
      </p>
      <p>
        <b>PRODUCTO:</b> {g.producto_nombre}
        {unidades(g)}
        {g.numero_serie && (
          <>
            <br />
            <b>SERIE / IMEI:</b> {g.numero_serie}
          </>
        )}
      </p>
      <p>
        <b>GARANTÍA:</b> {g.meses} {g.meses === 1 ? 'mes' : 'meses'}
        <br />
        <b>DESDE:</b> {fechaCorta(g.fecha_inicio)}
        <br />
        <b>HASTA:</b> {fechaCorta(g.vence_el)}
      </p>
      <div className="ticket-centro">
        <QrGarantia url={g.url_publica} clase="ticket-qr" />
        <small className="ticket-linea">Escanea para consultar tu garantía</small>
      </div>
      <footer>
        {g.condiciones.map((c) => (
          <small key={c}>{c} </small>
        ))}
      </footer>
    </article>
  )
}

/** Los formatos de impresión del certificado. */
export const especificacionCertificado = (g) => ({
  tipo: 'certificado-garantia',
  titulo: `Certificado de garantía ${g.comprobante_numero}`,
  subtitulo: g.cliente_nombre,
  formatos: { A4: <CertificadoGarantiaA4 garantia={g} />, TICKET: <CertificadoGarantiaTicket garantia={g} /> },
})
