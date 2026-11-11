import { Icono } from '../../../shared/components/IconosPanel'
import { fechaCorta, hoyIso } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import { useImpresionRecibo } from '../hooks/useImpresionRecibo'
import { estadoDeCuota } from '../ventas'

/** Las cuotas de un comprobante vendido a crédito y los abonos que ya se hicieron. */
export default function CuotasComprobante({ comprobante: c, moneda, puedeAnular, onAnularAbono }) {
  const hoy = hoyIso()
  const { imprimir, portal } = useImpresionRecibo()
  return (
    <>
      <h4>Cuotas</h4>
      <div className="marco-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th>Cuota</th>
              <th>Vence</th>
              <th className="num">Monto</th>
              <th className="num">Cobrado</th>
              <th className="num">Debe</th>
              <th>Estado</th>
            </tr>
          </thead>
          <tbody>
            {c.cuotas.map((q) => {
              const estado = estadoDeCuota(q, hoy)
              return (
                <tr key={q.id}>
                  <td>{q.numero}</td>
                  <td>{fechaCorta(q.fecha_vencimiento)}</td>
                  <td className="num">{dinero(q.monto, moneda)}</td>
                  <td className="num">{dinero(q.pagado, moneda)}</td>
                  <td className="num">{dinero(q.saldo, moneda)}</td>
                  <td>
                    <span className="pildora" data-tono={estado.tono}>
                      {estado.texto}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {c.abonos.length > 0 && (
        <>
          <h4>Abonos</h4>
          <ul className="venta-cobros">
            {c.abonos.map((a) => (
              <li key={a.id} className={a.anulado ? 'anulado' : undefined}>
                <span>
                  <strong>{a.medio_pago_nombre}</strong>
                  <span className="sub-texto">
                    {a.recibo_numero ? `Recibo ${a.recibo_numero} · ` : ''}
                    {fechaCorta(a.fecha)} · Entró a {a.cuenta_nombre}
                    {a.referencia ? ` · Op. ${a.referencia}` : ''}
                    {a.cuotas.length ? ` · Cuota${a.cuotas.length > 1 ? 's' : ''} ${a.cuotas.join(', ')}` : ''}
                    {Number(a.vuelto) > 0 ? ` · Recibido ${dinero(a.recibido, moneda)}, vuelto ${dinero(a.vuelto, moneda)}` : ''}
                    {a.anulado ? ` · Anulado: ${a.motivo_anulacion}` : ''}
                  </span>
                </span>
                <span className="venta-abono-monto">
                  <strong>{dinero(a.monto, moneda)}</strong>
                  {a.recibo && (
                    <button type="button" className="accion-icono" aria-label={`Imprimir el recibo ${a.recibo_numero}`} title="Imprimir recibo" onClick={() => imprimir(a.recibo)}>
                      <Icono nombre="documento" tam={17} />
                    </button>
                  )}
                  {puedeAnular && !a.anulado && (
                    <button type="button" className="accion-icono peligro-suave" aria-label="Anular este abono" title="Anular" onClick={() => onAnularAbono(a)}>
                      <Icono nombre="papelera" tam={17} />
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      {portal}
    </>
  )
}
