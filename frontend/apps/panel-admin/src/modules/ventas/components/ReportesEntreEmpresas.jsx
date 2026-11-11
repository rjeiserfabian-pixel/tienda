import { Tarjetas } from '../../caja/components/ReporteComun'
import { fechaCorta } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'

const nombreMoneda = (m) => (m === 'USD' ? 'dólares' : 'soles')
const DEVOLUCION = { NINGUNA: '', PARCIAL: 'Volvió una parte', TOTAL: 'Volvió todo' }

const Vacio = ({ texto }) => <p className="estado-vacio">{texto}</p>

/** Lo que pasó entre las empresas por las ventas internas, y cuánto de lo vendido salió del stock de la otra. */
export function VentasInternas({ datos }) {
  const { totales, con_mercaderia_de_la_otra: ajena } = datos
  const sinNada = datos.total_filas === 0 && ajena.lineas === 0
  if (sinNada) return <Vacio texto="No hubo ventas internas en ese periodo." />
  return (
    <>
      <dl className="cxp-tarjetas" aria-label="Resumen de ventas internas">
        <div>
          <dt>Entregó a la otra empresa</dt>
          <dd>{datos.con_utilidad ? dinero(totales.entregado.neto, 'PEN') : totales.entregado.cantidad}</dd>
          <small>
            {totales.entregado.cantidad} {totales.entregado.cantidad === 1 ? 'operación' : 'operaciones'}
            {datos.con_utilidad && Number(totales.entregado.devuelto) ? ` · le devolvieron ${dinero(totales.entregado.devuelto, 'PEN')}` : ''}
          </small>
        </div>
        <div>
          <dt>Recibió de la otra empresa</dt>
          <dd>{datos.con_utilidad ? dinero(totales.recibido.neto, 'PEN') : totales.recibido.cantidad}</dd>
          <small>
            {totales.recibido.cantidad} {totales.recibido.cantidad === 1 ? 'operación' : 'operaciones'}
            {datos.con_utilidad && Number(totales.recibido.devuelto) ? ` · devolvió ${dinero(totales.recibido.devuelto, 'PEN')}` : ''}
          </small>
        </div>
        {datos.con_utilidad && datos.por_liquidar.length > 0 && (
          <div data-tono="ambar">
            <dt>Por liquidar</dt>
            <dd>{dinero(datos.por_liquidar.reduce((suma, p) => suma + Number(p.monto), 0), 'PEN')}</dd>
            <small>{datos.por_liquidar.map((p) => `${p.pagadora} → ${p.receptora}`).join(' · ')}</small>
          </div>
        )}
      </dl>

      {ajena.lineas > 0 && (
        <dl className="cxp-tarjetas" aria-label="Vendido con mercadería de la otra empresa">
          <div>
            <dt>Vendido al cliente con mercadería de la otra empresa</dt>
            <dd>{dinero(ajena.neto, 'PEN')}</dd>
            <small>Sin IGV, en soles, restando devoluciones ({dinero(ajena.devuelto, 'PEN')})</small>
          </div>
          {datos.con_utilidad && (
            <div>
              <dt>Utilidad de esas ventas</dt>
              <dd>{dinero(ajena.utilidad, 'PEN')}</dd>
              <small>Costo: {dinero(ajena.costo, 'PEN')}. Queda toda en {datos.empresa_nombre}: la otra empresa le pasó la mercadería al costo.</small>
            </div>
          )}
        </dl>
      )}

      {datos.total_filas > 0 && (
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Venta interna</th>
                <th>Entrega → recibe</th>
                <th>Comprobante</th>
                <th>Devolución</th>
                <th>Liquidación</th>
                {datos.con_utilidad && (
                  <>
                    <th className="num">Costo trasladado</th>
                    <th className="num">Devuelto</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {datos.filas.map((f) => (
                <tr key={`${f.numero}-${f.entrega}`} className={f.estado === 'ANULADO' ? 'anulado' : undefined}>
                  <td>{fechaCorta(f.fecha)}</td>
                  <td>
                    <strong>N° {f.numero}</strong>
                    <span className="sub-texto">{f.documento}{f.estado === 'ANULADO' ? ' · Anulada' : ''}</span>
                  </td>
                  <td>
                    {f.entrega} → {f.recibe}
                  </td>
                  <td className="celda-suave">{f.comprobante || '—'}</td>
                  <td className="celda-suave">{DEVOLUCION[f.devolucion]}</td>
                  <td className="celda-suave">{f.liquidacion || '—'}</td>
                  {datos.con_utilidad && (
                    <>
                      <td className="num">{dinero(f.costo, 'PEN')}</td>
                      <td className="num celda-suave">{Number(f.devuelto) ? dinero(f.devuelto, 'PEN') : ''}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {datos.truncado && <p className="celda-suave">Se muestran las últimas {datos.filas.length} de {datos.total_filas}. El Excel trae todas.</p>}
    </>
  )
}

/** Lo vendido a clientes por cada empresa y el total de todas. La venta interna no suma: es la misma mercadería. */
export function Consolidado({ datos }) {
  if (datos.totales.length === 0) return <Vacio texto="No hubo ventas en ese periodo." />
  return (
    <>
      <Tarjetas titulo="Ventas netas de todas las empresas" filas={datos.totales} clave="neto" etiqueta={(t) => `Vendido en ${nombreMoneda(t.moneda)} (neto)`} />
      {datos.con_utilidad && (
        <dl className="cxp-tarjetas" aria-label="Utilidad de todas las empresas">
          {datos.totales.map((t) => (
            <div key={t.moneda}>
              <dt>Utilidad en {nombreMoneda(t.moneda)}</dt>
              <dd>{dinero(t.utilidad, 'PEN')}</dd>
              <small>Costo: {dinero(t.costo, 'PEN')} (en soles)</small>
            </div>
          ))}
        </dl>
      )}
      <div className="marco-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th>Empresa</th>
              <th>Moneda</th>
              <th className="num">Comprobantes</th>
              <th className="num">Sin IGV</th>
              <th className="num">IGV</th>
              <th className="num">Total</th>
              <th className="num">Notas de crédito</th>
              <th className="num">Neto</th>
              {datos.con_utilidad && <th className="num">Utilidad (S/)</th>}
            </tr>
          </thead>
          <tbody>
            {datos.empresas.flatMap((e) =>
              e.totales.map((t) => (
                <tr key={`${e.empresa}-${t.moneda}`}>
                  <td>{e.nombre}</td>
                  <td className="celda-suave">{nombreMoneda(t.moneda)}</td>
                  <td className="num">{t.cantidad}</td>
                  <td className="num">{dinero(t.valor, t.moneda)}</td>
                  <td className="num">{dinero(t.igv, t.moneda)}</td>
                  <td className="num">{dinero(t.total, t.moneda)}</td>
                  <td className="num celda-suave">{Number(t.notas) ? dinero(t.notas, t.moneda) : ''}</td>
                  <td className="num">
                    <strong>{dinero(t.neto, t.moneda)}</strong>
                  </td>
                  {datos.con_utilidad && <td className="num">{dinero(t.utilidad, 'PEN')}</td>}
                </tr>
              )),
            )}
          </tbody>
          <tfoot>
            {datos.totales.map((t) => (
              <tr key={`total-${t.moneda}`}>
                <th>Total de las empresas</th>
                <th className="celda-suave">{nombreMoneda(t.moneda)}</th>
                <th className="num">{t.cantidad}</th>
                <th className="num">{dinero(t.valor, t.moneda)}</th>
                <th className="num">{dinero(t.igv, t.moneda)}</th>
                <th className="num">{dinero(t.total, t.moneda)}</th>
                <th className="num">{Number(t.notas) ? dinero(t.notas, t.moneda) : ''}</th>
                <th className="num">{dinero(t.neto, t.moneda)}</th>
                {datos.con_utilidad && <th className="num">{dinero(t.utilidad, 'PEN')}</th>}
              </tr>
            ))}
          </tfoot>
        </table>
      </div>
      {datos.ventas_internas.cantidad > 0 && (
        <p className="celda-suave">
          No se suman {datos.ventas_internas.cantidad} {datos.ventas_internas.cantidad === 1 ? 'venta interna' : 'ventas internas'}
          {datos.con_utilidad ? ` (${dinero(datos.ventas_internas.costo, 'PEN')} al costo)` : ''}: es la misma mercadería pasando de una empresa a la otra. Lo que se vendió al cliente cuenta una sola vez, en la empresa que emitió el comprobante.
        </p>
      )}
    </>
  )
}
