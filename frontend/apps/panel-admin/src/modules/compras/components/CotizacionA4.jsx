import { fechaCorta } from '../../almacen/inventario'
import { ESTADOS_COTIZACION } from '../cotizaciones'

const cantidad = (valor) => Number(valor).toLocaleString('es-PE', { maximumFractionDigits: 3 })

const Dato = ({ etiqueta, valor }) => (
  <p>
    <b>{etiqueta}</b>
    <span>: {valor || '—'}</span>
  </p>
)

const LINEA_PARA_LLENAR = { display: 'inline-block', minWidth: 180, borderBottom: '1px solid #000' }

/**
 * La solicitud de cotización en hoja A4, para entregarla o enviarla al proveedor. NO lleva precios:
 * trae una columna vacía donde el proveedor escribe el suyo, y espacio para sus condiciones.
 * `proveedor` (opcional) es el nombre de a quién va dirigida.
 */
export default function CotizacionA4({ datos: c, proveedor }) {
  const e = c.emisor
  const borrador = c.estado === 'BORRADOR'
  return (
    <article className="documento documento-venta" aria-label={`Solicitud de cotización ${c.codigo}`}>
      <header>
        <div>
          <h1>{e.nombre}</h1>
        </div>
        <div className="documento-caja">
          <span>RUC {e.ruc}</span>
          <strong>SOLICITUD DE COTIZACIÓN</strong>
          <strong>{c.codigo}</strong>
          {borrador && <b className="documento-anulado">{ESTADOS_COTIZACION[c.estado].texto.toUpperCase()}</b>}
          {c.estado === 'ANULADA' && <b className="documento-anulado">ANULADA</b>}
        </div>
      </header>

      <section className="documento-cliente">
        <div>
          <Dato etiqueta="PROVEEDOR" valor={proveedor} />
          <Dato etiqueta="FECHA" valor={fechaCorta(c.fecha)} />
          <Dato etiqueta="RESPONDER HASTA" valor={c.fecha_limite ? fechaCorta(c.fecha_limite) : ''} />
        </div>
        <div>
          <Dato etiqueta="ENTREGAR EN" valor={c.almacen_nombre} />
          <Dato etiqueta="MONEDA" valor={c.moneda === 'USD' ? 'Dólares' : 'Soles'} />
          <Dato etiqueta="PRECIOS" valor={c.precios_incluyen_igv ? 'Con IGV incluido' : 'Sin IGV'} />
        </div>
      </section>

      <table className="documento-items">
        <thead>
          <tr>
            <th>ITEM</th>
            <th>CANT.</th>
            <th>DESCRIPCIÓN</th>
            <th>U.M.</th>
            <th>PRECIO UNIT.</th>
          </tr>
        </thead>
        <tbody>
          {c.lineas.map((l) => (
            <tr key={l.id}>
              <td>{l.posicion}</td>
              <td>{cantidad(l.cantidad)}</td>
              <td>
                {l.producto_nombre}
                <small style={{ display: 'block' }}>{l.producto_codigo}</small>
              </td>
              <td>{l.unidad}</td>
              <td aria-label="Para que el proveedor escriba su precio" />
            </tr>
          ))}
        </tbody>
      </table>

      {c.observacion && <p style={{ fontSize: 11 }}>Observación: {c.observacion}</p>}

      <section style={{ fontSize: 12, lineHeight: 2.2 }} aria-label="Condiciones del proveedor">
        <p>
          Forma de pago: <span style={LINEA_PARA_LLENAR} />
          &nbsp;&nbsp; Entrega en (días): <span style={{ ...LINEA_PARA_LLENAR, minWidth: 80 }} />
        </p>
        <p>
          Precios válidos hasta: <span style={LINEA_PARA_LLENAR} />
        </p>
      </section>

      <footer className="documento-pie">
        <div>
          <span>Atendido por: ______________________________</span>
        </div>
        <div>
          <small>Solicitud de cotización {c.codigo}. Esta solicitud no es una orden de compra ni compromete a comprar.</small>
        </div>
      </footer>
    </article>
  )
}
