import { cantidad, fechaCorta } from '../../almacen/inventario'
import { datosDeTransporte, lugarConUbigeo, origenDeGuia } from '../ventas'
import { Logo } from './TicketPartes'

/** La guía de remisión en hoja A4: quién envía, a quién, de dónde a dónde, quién la lleva y qué viaja con su peso. */
export default function GuiaImpresa({ guia: g }) {
  const transporte = datosDeTransporte(g)
  const origen = origenDeGuia(g)
  return (
    <article className="documento" aria-label={`Guía de remisión ${g.numero_completo}`}>
      <header>
        <div>
          {g.emisor.tiene_logo && <Logo empresa={g.emisor.empresa} />}
          <h1>{g.emisor.nombre}</h1>
          <span>RUC {g.emisor.ruc}</span>
          {g.emisor.direccion && <span>{g.emisor.direccion}</span>}
        </div>
        <div className="documento-numero">
          <h1>GUÍA DE REMISIÓN</h1>
          <strong>{g.numero_completo}</strong>
          <span>Emisión: {fechaCorta(g.fecha_emision)}</span>
          <span>Inicio del traslado: {fechaCorta(g.fecha_traslado)}</span>
          <span>
            {origen.etiqueta}: {origen.valor}
          </span>
        </div>
      </header>
      <p>
        <strong>Destinatario:</strong> {g.destinatario_nombre}
        {g.destinatario_documento ? ` · ${g.destinatario_tipo_documento ? `${g.destinatario_tipo_documento} ` : ''}${g.destinatario_documento}` : ''}
        <br />
        <strong>Punto de partida:</strong> {lugarConUbigeo(g.punto_partida, g.ubigeo_partida_nombre)}
        <br />
        <strong>Punto de llegada:</strong> {lugarConUbigeo(g.punto_llegada, g.ubigeo_llegada_nombre)}
        <br />
        <strong>Motivo del traslado:</strong> {g.motivo_nombre}
        {g.almacen_origen_nombre && (
          <>
            <br />
            <strong>Almacén de origen:</strong> {g.almacen_origen_nombre}
          </>
        )}
      </p>
      <p>
        <strong>Transporte:</strong> {g.modalidad_nombre}
        {transporte.map(([etiqueta, valor]) => (
          <span key={etiqueta}>
            <br />
            <strong>{etiqueta}:</strong> {valor}
          </span>
        ))}
      </p>
      <table>
        <thead>
          <tr>
            <th>N°</th>
            <th>Descripción</th>
            <th>Unidad</th>
            <th>Cantidad</th>
            <th>Peso (kg)</th>
          </tr>
        </thead>
        <tbody>
          {g.lineas.map((l, i) => (
            <tr key={l.id}>
              <td>{i + 1}</td>
              <td>{l.descripcion}</td>
              <td>{l.unidad}</td>
              <td>{cantidad(l.cantidad)}</td>
              <td>{Number(l.peso_kg) > 0 ? Number(l.peso_kg) : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <footer>
        <div>
          Bultos: {g.bultos}
          {Number(g.peso_kg) > 0 ? ` · Peso total: ${Number(g.peso_kg)} kg` : ''}
        </div>
        {g.observacion && <div>Observación: {g.observacion}</div>}
        <div>Emitida por {g.emitida_por_nombre || '—'}. Documento interno de traslado.</div>
      </footer>
    </article>
  )
}
