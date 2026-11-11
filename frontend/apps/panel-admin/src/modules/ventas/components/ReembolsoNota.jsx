import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import { dinero } from '../../compras/compras'
import { aDinero, cobroNuevo, totalCobrado } from '../ventas'

/**
 * Cómo se le devuelve el dinero al cliente: una fila por método (método, monto y, si hace falta, el
 * número de operación). Llega prellenado por los métodos con que pagó; se puede cambiar, dividir o
 * quitar, pero la suma debe ser exactamente lo que se devuelve en dinero.
 */
export default function ReembolsoNota({ medios, cobros, aReembolsarCts, moneda, disabled, onCobros }) {
  const poner = (id, campos) => onCobros(cobros.map((c) => (c.id === id ? { ...c, ...campos } : c)))
  const falta = aReembolsarCts - totalCobrado(cobros)
  const medioLibre = medios.find((m) => m.tipo === 'EFECTIVO') ?? medios[0]

  return (
    <div className="compra-pagos">
      {cobros.map((c, i) => {
        const medio = medios.find((m) => m.id === c.medio)
        return (
          <div key={c.id} className="compra-pago-fila">
            <Campo etiqueta={i === 0 ? 'Devolver por' : `Devolver por (${i + 1})`} tipo="select">
              {(p) => (
                <select {...p} value={c.medio} disabled={disabled} onChange={(e) => poner(c.id, { medio: Number(e.target.value), referencia: '' })}>
                  {medios.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.nombre}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Monto" clase="compra-monto">
              {(p) => <input {...p} inputMode="decimal" value={c.monto} disabled={disabled} onChange={(e) => poner(c.id, { monto: e.target.value.replace(',', '.') })} />}
            </Campo>
            {medio?.requiere_referencia && (
              <Campo etiqueta="N° de operación" clase="compra-referencia" requerido>
                {(p) => <input {...p} maxLength={60} value={c.referencia} disabled={disabled} onChange={(e) => poner(c.id, { referencia: e.target.value })} />}
              </Campo>
            )}
            <button type="button" className="accion-icono peligro-suave compra-quitar" aria-label={`Quitar la devolución ${i + 1}`} title="Quitar" disabled={disabled} onClick={() => onCobros(cobros.filter((x) => x.id !== c.id))}>
              <Icono nombre="papelera" tam={19} />
            </button>
          </div>
        )
      })}
      <div className="compra-pagos-pie">
        <button type="button" disabled={disabled || !medioLibre || falta <= 0} onClick={() => onCobros([...cobros, cobroNuevo(medioLibre.id, Math.max(falta, 0))])}>
          <Icono nombre="agregar" tam={18} /> Dividir la devolución
        </button>
        <dl className="compra-totales pos-resumen-cobro">
          <div>
            <dt>Devuelto</dt>
            <dd>{dinero(aDinero(totalCobrado(cobros)), moneda)}</dd>
          </div>
          {falta !== 0 && (
            <div>
              <dt>{falta > 0 ? 'Falta devolver' : 'Se pasa por'}</dt>
              <dd className={falta > 0 ? 'pos-falta' : 'pos-sobra'}>{dinero(aDinero(Math.abs(falta)), moneda)}</dd>
            </div>
          )}
        </dl>
      </div>
    </div>
  )
}
