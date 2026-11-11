import Campo from '../../../shared/components/Campo'
import { fechaCorta } from '../../almacen/inventario'
import { dinero, FORMAS_PAGO } from '../compras'
import PagosContado from './PagosContado'

/** Crédito: número de cuotas, primera fecha y periodicidad; muestra el cronograma que calcula el servidor. */
function CuotasCredito({ cuotas, onCuotas, periodicidades, periodicidadId, cronograma, moneda, errores, minimo, disabled }) {
  const poner = (campo) => (ev) => onCuotas((previas) => ({ ...previas, [campo]: ev.target.value }))
  // La primera cuota no puede vencer antes de la emisión: una fecha anterior se lleva a la de emisión.
  const primera = cuotas.primera && cuotas.primera < minimo ? minimo : cuotas.primera

  return (
    <div className="compra-credito">
      <div className="fila-campos">
        <Campo etiqueta="Número de cuotas" error={errores.cuotas} ayuda="Un plazo único es 1 cuota.">
          {(c) => <input {...c} type="number" min={1} max={60} value={cuotas.cantidad} disabled={disabled} onChange={poner('cantidad')} />}
        </Campo>
        <Campo etiqueta="Vence la primera cuota" icono="calendario" error={errores.primera}>
          {(c) => <input {...c} type="date" min={minimo} value={primera} disabled={disabled} onChange={(ev) => onCuotas((previas) => ({ ...previas, primera: ev.target.value && ev.target.value < minimo ? minimo : ev.target.value }))} />}
        </Campo>
        <Campo etiqueta="Cada" tipo="select" error={errores.periodicidad}>
          {(c) => (
            <select {...c} value={periodicidadId} disabled={disabled} onChange={poner('periodicidad')}>
              {periodicidades.length === 0 && <option value="">Sin periodicidades</option>}
              {periodicidades.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.nombre}
                </option>
              ))}
            </select>
          )}
        </Campo>
      </div>
      {cronograma?.length > 0 && (
        <div className="marco-tabla compra-cronograma">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th className="centrado">Cuota</th>
                <th>Vence</th>
                <th className="num">Monto</th>
              </tr>
            </thead>
            <tbody>
              {cronograma.map((c) => (
                <tr key={c.numero}>
                  <td className="centrado">{c.numero}</td>
                  <td>{fechaCorta(c.fecha_vencimiento)}</td>
                  <td className="num">{dinero(c.monto, moneda)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/** Forma de pago de la compra: contado o crédito, con lo que cada una necesita. */
export default function FormaPagoCompra({ b, poner, ...resto }) {
  return (
    <>
      <div className="segmentos" role="radiogroup" aria-label="Forma de pago">
        {Object.entries(FORMAS_PAGO).map(([valor, texto]) => (
          <button key={valor} type="button" role="radio" aria-checked={b.forma === valor} className={b.forma === valor ? 'activo' : undefined} disabled={resto.disabled} onClick={() => poner('forma', valor)}>
            {texto}
          </button>
        ))}
      </div>
      {b.forma === 'CONTADO' ? (
        <PagosContado
          resueltos={resto.resueltos}
          cuentas={resto.cuentas}
          medios={resto.medios}
          moneda={b.moneda}
          total={resto.total}
          errores={resto.erroresPagos}
          sinPermisoCajas={resto.sinPermisoCajas}
          onPagos={(f) => poner('pagos', f)}
          disabled={resto.disabled}
        />
      ) : (
        <CuotasCredito
          cuotas={b.cuotas}
          onCuotas={(f) => poner('cuotas', f)}
          periodicidades={resto.periodicidades}
          periodicidadId={resto.periodicidadId}
          minimo={b.fecha}
          cronograma={resto.cronograma}
          moneda={b.moneda}
          errores={resto.errores}
          disabled={resto.disabled}
        />
      )}
    </>
  )
}
