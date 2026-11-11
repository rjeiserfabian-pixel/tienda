import { fechaCorta, mesAnio, numero, soles } from '../rrhh'

const Dato = ({ etiqueta, valor }) => (
  <p>
    <b>{etiqueta}</b>
    <span>: {valor || '—'}</span>
  </p>
)

function Detalle({ titulo, lineas, total }) {
  return (
    <table className="documento-items">
      <thead>
        <tr>
          <th>{titulo}</th>
          <th>IMPORTE</th>
        </tr>
      </thead>
      <tbody>
        {lineas.length === 0 && (
          <tr>
            <td colSpan={2}>—</td>
          </tr>
        )}
        {lineas.map((l, i) => (
          <tr key={`${l.nombre}-${i}`}>
            <td>
              {l.nombre}
              {l.detalle && <small style={{ display: 'block' }}>{l.detalle}</small>}
            </td>
            <td>{soles(l.monto)}</td>
          </tr>
        ))}
        {total !== undefined && (
          <tr>
            <td>
              <strong>TOTAL</strong>
            </td>
            <td>
              <strong>{soles(total)}</strong>
            </td>
          </tr>
        )}
      </tbody>
    </table>
  )
}

/** La boleta de pago de un trabajador en hoja A4: sus ingresos, descuentos, el neto y los aportes de la empresa. */
export default function BoletaA4({ datos: b }) {
  const t = b.trabajador
  return (
    <article className="documento documento-venta" aria-label={`Boleta de pago de ${t.nombre}`}>
      <header>
        <div>
          <h1>{b.emisor.nombre}</h1>
          {b.emisor.direccion && <span>{b.emisor.direccion}</span>}
        </div>
        <div className="documento-caja">
          <span>RUC {b.emisor.ruc}</span>
          <strong>BOLETA DE PAGO</strong>
          <strong style={{ textTransform: 'uppercase' }}>{mesAnio(b.periodo)}</strong>
          {b.es_borrador && <b className="documento-anulado">BORRADOR</b>}
        </div>
      </header>

      <section className="documento-cliente">
        <div>
          <Dato etiqueta="TRABAJADOR" valor={t.nombre} />
          <Dato etiqueta={t.tipo_documento || 'DOCUMENTO'} valor={t.numero_documento} />
          <Dato etiqueta="CARGO" valor={t.cargo} />
          <Dato etiqueta="INGRESO" valor={t.fecha_ingreso ? fechaCorta(t.fecha_ingreso) : ''} />
        </div>
        <div>
          <Dato etiqueta="RÉGIMEN" valor={t.regimen} />
          <Dato etiqueta="PENSIÓN" valor={t.pension} />
          <Dato etiqueta="DÍAS TRABAJADOS" valor={`${b.dias_laborados} (faltas: ${b.dias_falta})`} />
          <Dato etiqueta="HORAS" valor={`${numero(b.horas_trabajadas)} (extra: ${numero(b.horas_extra)})`} />
        </div>
      </section>

      <Detalle titulo="INGRESOS" lineas={b.ingresos} total={b.total_ingresos} />
      <Detalle titulo="DESCUENTOS" lineas={b.descuentos} total={b.total_descuentos} />
      {b.aportes_empleador.length > 0 && <Detalle titulo="APORTES DE LA EMPRESA (no se descuentan)" lineas={b.aportes_empleador} />}

      <table className="documento-totales">
        <thead>
          <tr>
            <th>NETO A PAGAR</th>
            <th>PAGO</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <strong>{soles(b.neto)}</strong>
            </td>
            <td>{b.pago ? `Pagado el ${fechaCorta(b.pago.fecha)}${b.pago.medio ? ` · ${b.pago.medio}` : ''}${b.pago.referencia ? ` · Op. ${b.pago.referencia}` : ''}` : 'Por pagar'}</td>
          </tr>
        </tbody>
      </table>

      <footer className="documento-pie">
        <div>
          <span>Recibí conforme: ______________________________</span>
        </div>
        <div>
          <small>Boleta de pago de remuneraciones. Conserve este documento.</small>
        </div>
      </footer>
    </article>
  )
}
