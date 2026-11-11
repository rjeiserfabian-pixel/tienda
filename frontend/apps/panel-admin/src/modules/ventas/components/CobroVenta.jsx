import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import { dinero } from '../../compras/compras'
import { aDinero, atajosDeBilletes, cobroNuevo, disponibilidadDeCobro, faltaCobrar, medioPorDefecto, totalCobrado, vueltoDe } from '../ventas'

/**
 * Los cobros de la venta, como los pagos de una compra: una fila por método (método, monto y, si
 * hace falta, N° de operación o efectivo recibido). Al contado la primera fila toma sola el total y
 * «Dividir el cobro» agrega otra con lo que falta. A crédito el pago inicial es opcional.
 */
export default function CobroVenta({ config, medios, cobros, credito = false, totalCts, moneda, empresasDelCarrito, disabled, onCobros }) {
  const falta = faltaCobrar(totalCts, cobros)
  const vueltoTotal = cobros.reduce((suma, c) => suma + vueltoDe(c), 0)
  const poner = (id, campos) => onCobros(cobros.map((c) => (c.id === id ? { ...c, ...campos } : c)))
  const disponible = (m) => disponibilidadDeCobro(m, config, moneda, empresasDelCarrito)
  const nuevoMedio = () => medioPorDefecto(medios, config, moneda, empresasDelCarrito)
  const agregar = () => {
    const medio = nuevoMedio()
    if (!medio) return
    // Las filas que seguían al total conservan lo que mostraban; la nueva toma lo que falta.
    const fijas = cobros.map((c) => ({ ...c, auto: false }))
    onCobros([...fijas, cobroNuevo(medio.id, credito ? 0 : Math.max(falta, 0), false)])
  }
  const quitar = (id) => {
    const quedan = cobros.filter((c) => c.id !== id)
    onCobros(!credito && quedan.length === 1 ? [{ ...quedan[0], auto: true }] : quedan)
  }
  const sinDonde = medios.every((m) => !disponible(m).ok)

  if (totalCts <= 0) return <p className="celda-suave">Agrega productos para poder cobrar.</p>
  if (sinDonde) return <p role="alert" className="compra-aviso">Ningún método de pago tiene caja o cuenta configurada en todas las empresas de esta venta.</p>

  return (
    <div className="compra-pagos">
      {credito && cobros.length === 0 && <p className="celda-suave">Pago inicial: opcional. Si el cliente paga una parte ahora, agrégala; el resto queda en cuotas por cobrar.</p>}
      {cobros.map((c, i) => {
        const medio = medios.find((m) => m.id === c.medio)
        const esEfectivo = medio?.tipo === 'EFECTIVO'
        const vuelto = vueltoDe(c)
        return (
          <div key={c.id} className="compra-pago-bloque">
            <div className="compra-pago-fila">
              <Campo etiqueta={credito ? 'Método del pago inicial' : i === 0 ? 'Método de pago' : `Método (cobro ${i + 1})`} tipo="select">
                {(p) => (
                  <select {...p} value={c.medio} disabled={disabled} onChange={(e) => poner(c.id, { medio: Number(e.target.value), referencia: '', recibido: '' })}>
                    {medios.map((m) => (
                      <option key={m.id} value={m.id} disabled={!disponible(m).ok && m.id !== c.medio} title={disponible(m).ok ? undefined : disponible(m).motivo}>
                        {m.nombre}
                        {disponible(m).ok ? '' : ' (sin caja o cuenta)'}
                      </option>
                    ))}
                  </select>
                )}
              </Campo>
              <Campo etiqueta="Monto" clase="compra-monto">
                {(p) => <input {...p} inputMode="decimal" value={c.monto} disabled={disabled} onChange={(e) => poner(c.id, { monto: e.target.value.replace(',', '.'), auto: false })} />}
              </Campo>
              {medio?.requiere_referencia && (
                <Campo etiqueta="N° de operación" clase="compra-referencia">
                  {(p) => <input {...p} maxLength={60} value={c.referencia} disabled={disabled} onChange={(e) => poner(c.id, { referencia: e.target.value })} />}
                </Campo>
              )}
              {esEfectivo && (
                <Campo etiqueta="Efectivo recibido" clase="compra-monto" ayuda="Para calcular el vuelto.">
                  {(p) => <input {...p} inputMode="decimal" placeholder={c.monto} value={c.recibido} disabled={disabled} onChange={(e) => poner(c.id, { recibido: e.target.value.replace(',', '.') })} />}
                </Campo>
              )}
              {(cobros.length > 1 || credito) && (
                <button type="button" className="accion-icono peligro-suave compra-quitar" aria-label={`Quitar el cobro ${i + 1}`} title="Quitar" disabled={disabled} onClick={() => quitar(c.id)}>
                  <Icono nombre="papelera" tam={19} />
                </button>
              )}
            </div>
            {esEfectivo && (
              <div className="pos-atajos" role="group" aria-label="Billetes">
                <button type="button" disabled={disabled} onClick={() => poner(c.id, { recibido: '' })}>
                  Exacto
                </button>
                {atajosDeBilletes(Math.round((Number(c.monto) || 0) * 100)).map((b) => (
                  <button key={b} type="button" disabled={disabled} onClick={() => poner(c.id, { recibido: String(b) })}>
                    {moneda === 'USD' ? 'US$' : 'S/'} {b}
                  </button>
                ))}
              </div>
            )}
            {vuelto > 0 && (
              <p className="pos-vuelto" role="status">
                Vuelto: <strong>{dinero(aDinero(vuelto), moneda)}</strong>
              </p>
            )}
          </div>
        )
      })}

      <div className="compra-pagos-pie">
        <button type="button" disabled={disabled || !nuevoMedio() || (!credito && cobros.length > 0 && falta <= 0)} onClick={agregar}>
          <Icono nombre="agregar" tam={18} /> {credito ? (cobros.length === 0 ? 'Agregar pago inicial' : 'Agregar otro pago') : 'Dividir el cobro'}
        </button>
        {cobros.length > 0 && (
          <dl className="compra-totales pos-resumen-cobro">
            <div>
              <dt>{credito ? 'Pago inicial' : 'Cobrado'}</dt>
              <dd>{dinero(aDinero(totalCobrado(cobros)), moneda)}</dd>
            </div>
            {falta !== 0 && !credito && (
              <div>
                <dt>{falta > 0 ? 'Falta cobrar' : 'Se pasa por'}</dt>
                <dd className={falta > 0 ? 'pos-falta' : 'pos-sobra'}>{dinero(aDinero(Math.abs(falta)), moneda)}</dd>
              </div>
            )}
            {vueltoTotal > 0 && (
              <div>
                <dt>Vuelto total</dt>
                <dd>{dinero(aDinero(vueltoTotal), moneda)}</dd>
              </div>
            )}
          </dl>
        )}
      </div>
    </div>
  )
}
