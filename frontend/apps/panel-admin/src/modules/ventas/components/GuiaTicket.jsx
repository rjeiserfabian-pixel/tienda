import { cantidad, fechaCorta } from '../../almacen/inventario'
import { datosDeTransporte, lugarConUbigeo, origenDeGuia } from '../ventas'
import { EmisorTicket } from './TicketPartes'

/** La guía de remisión en ticket de 80 mm: quién envía, a quién, de dónde a dónde, quién la lleva y qué viaja. */
export default function GuiaTicket({ guia: g }) {
  const origen = origenDeGuia(g)
  return (
    <article className="ticket" aria-label={`Guía de remisión ${g.numero_completo}`}>
      <EmisorTicket emisor={g.emisor} titulo="GUÍA DE REMISIÓN" numero={g.numero_completo} />
      <p>
        <b>EMISIÓN:</b> {fechaCorta(g.fecha_emision)}
        <br />
        <b>INICIO DEL TRASLADO:</b> {fechaCorta(g.fecha_traslado)}
        <br />
        <b>{origen.etiqueta.toUpperCase()}:</b> {origen.valor}
      </p>
      <p>
        <b>DESTINATARIO</b>
        <br />
        {g.destinatario_documento ? `${g.destinatario_documento} · ` : ''}
        {g.destinatario_nombre}
        <br />
        <b>PARTIDA:</b> {lugarConUbigeo(g.punto_partida, g.ubigeo_partida_nombre)}
        <br />
        <b>LLEGADA:</b> {lugarConUbigeo(g.punto_llegada, g.ubigeo_llegada_nombre)}
        <br />
        <b>MOTIVO:</b> {g.motivo_nombre}
      </p>
      <p>
        <b>TRANSPORTE:</b> {g.modalidad_nombre}
        {datosDeTransporte(g).map(([etiqueta, valor]) => (
          <span key={etiqueta}>
            <br />
            {etiqueta}: {valor}
          </span>
        ))}
      </p>
      <table>
        <thead>
          <tr>
            <th>N°</th>
            <th>Descripción</th>
            <th>Cant.</th>
          </tr>
        </thead>
        <tbody>
          {g.lineas.map((l, i) => (
            <tr key={l.id}>
              <td>{i + 1}</td>
              <td>
                {l.descripcion}
                <small>
                  {' '}
                  · {l.unidad}
                  {Number(l.peso_kg) > 0 ? ` · ${Number(l.peso_kg)} kg` : ''}
                </small>
              </td>
              <td>{cantidad(l.cantidad)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        Bultos: {g.bultos}
        {Number(g.peso_kg) > 0 ? ` · Peso total: ${Number(g.peso_kg)} kg` : ''}
        {g.observacion && (
          <>
            <br />
            Observación: {g.observacion}
          </>
        )}
      </p>
      <footer>
        <small>Emitida por {g.emitida_por_nombre || '—'}. Documento interno de traslado.</small>
      </footer>
    </article>
  )
}
