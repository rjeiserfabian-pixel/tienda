import { Link } from 'react-router-dom'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import { dinero, nuevoPago, totalPagado } from '../compras'

/**
 * Una o varias filas de pago (método, caja o cuenta, monto, N° de operación). La primera toma sola
 * el total. Al registrar una compra al contado los pagos deben sumar el total; al pagar una deuda
 * (`amortizar`) pueden sumar menos y el resto queda pendiente. Con `entra` es dinero que VUELVE
 * (reembolso de un proveedor): se dice a qué cuenta entra, no hay aporte de socio y, con
 * `restoComo="saldo"`, lo que no se reembolse queda como saldo a favor.
 */
export default function PagosContado({ resueltos, cuentas, medios, moneda, total, errores, sinPermisoCajas, onPagos, disabled, amortizar = false, entra = false, restoComo = 'pendiente' }) {
  const cambiar = (id, cambios) => onPagos((previos) => previos.map((p) => (p.id === id ? { ...p, ...cambios } : p)))
  // Al agregar otro pago, los anteriores conservan lo que mostraban y el nuevo toma lo que falta.
  const agregar = () => onPagos((previos) => [...previos.map((p) => { const r = resueltos.find((x) => x.id === p.id); return r && p.auto ? { ...p, auto: false, monto: r.monto } : p }), nuevoPago()])
  const quitar = (id) => onPagos((previos) => (previos.length > 1 ? previos.filter((p) => p.id !== id).map((p, i, resto) => (i === resto.length - 1 ? { ...p, auto: true } : p)) : previos))
  const pagado = totalPagado(resueltos)
  const diferencia = total === null ? null : Math.round((Number(total) - pagado) * 100) / 100

  if (sinPermisoCajas) {
    return <p role="alert" className="compra-aviso">No tienes acceso a las cajas y cuentas de esta empresa. Pide el permiso «Ver cajas y cuentas» {entra ? 'para registrar el reembolso.' : amortizar ? 'para poder pagar.' : 'o registra la compra al crédito.'}</p>
  }
  if (cuentas.length === 0) {
    return (
      <p role="alert" className="compra-aviso">
        No hay cajas o cuentas para esta empresa. <Link to="/caja/cuentas">Créalas aquí</Link> {entra ? 'para registrar el reembolso.' : amortizar ? 'para poder pagar.' : 'para poder pagar al contado.'}
      </p>
    )
  }

  return (
    <div className="compra-pagos">
      {resueltos.map((p, i) => {
        const e = errores[p.id] ?? {}
        return (
          <div className="compra-pago-fila" key={p.id}>
            <Campo etiqueta={i === 0 ? 'Método de pago' : `Método (pago ${i + 1})`} tipo="select" error={e.medio}>
              {(c) => (
                <select {...c} value={p.medio} disabled={disabled} onChange={(ev) => cambiar(p.id, { medio: ev.target.value, referencia: '' })}>
                  {medios.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.nombre}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta={entra ? 'Entra a' : 'Sale de'} tipo="select" error={e.cuenta}>
              {(c) => (
                <select {...c} value={p.cuenta} disabled={disabled} onChange={(ev) => cambiar(p.id, { cuenta: ev.target.value })}>
                  <option value="">Elija la caja o cuenta</option>
                  {[...cuentas].sort((a, b) => Number(b.moneda === moneda) - Number(a.moneda === moneda)).map((cu) => (
                    <option key={cu.id} value={cu.id}>
                      {cu.nombre} ({cu.moneda === 'USD' ? 'US$' : 'S/'})
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Monto" clase="compra-monto" error={e.monto}>
              {(c) => <input {...c} inputMode="decimal" value={p.monto} disabled={disabled} onChange={(ev) => cambiar(p.id, { monto: ev.target.value, auto: false })} />}
            </Campo>
            {p.otraMoneda && (
              <Campo etiqueta="Tipo de cambio" clase="compra-monto" error={e.tipoCambio}>
                {(c) => <input {...c} inputMode="decimal" placeholder="3.75" value={p.tipoCambio} disabled={disabled} onChange={(ev) => cambiar(p.id, { tipoCambio: ev.target.value })} />}
              </Campo>
            )}
            {p.pideReferencia && (
              <Campo etiqueta="N° de operación" clase="compra-referencia" error={e.referencia}>
                {(c) => <input {...c} maxLength={60} value={p.referencia} disabled={disabled} onChange={(ev) => cambiar(p.id, { referencia: ev.target.value })} />}
              </Campo>
            )}
            {p.otraMoneda && p.montoCuenta !== null && (
              <p className="sub-texto compra-sale" aria-live="polite">
                {entra ? 'Entra a la cuenta' : 'Sale de la cuenta'}: <strong>{dinero(p.montoCuenta, p.monedaCuenta)}</strong>
              </p>
            )}
            {!entra && (
              <label className="compra-aporte" title="El dinero entra a la caja como aporte del socio y este pago lo gasta: la caja no queda en negativo.">
                <input type="checkbox" checked={Boolean(p.aporte)} disabled={disabled} onChange={(ev) => cambiar(p.id, { aporte: ev.target.checked })} /> Lo pagó un socio de su bolsillo (se registra como aporte)
              </label>
            )}
            {resueltos.length > 1 && (
              <button type="button" className="accion-icono peligro-suave compra-quitar" aria-label={`Quitar el pago ${i + 1}`} title="Quitar" disabled={disabled} onClick={() => quitar(p.id)}>
                <Icono nombre="papelera" tam={19} />
              </button>
            )}
          </div>
        )
      })}
      <div className="compra-pagos-pie">
        <button type="button" className="boton-cabecera" disabled={disabled || resueltos.length >= 20} onClick={agregar}>
          <Icono nombre="agregar" tam={19} /> Dividir el pago
        </button>
        {diferencia !== null && (
          <span className="compra-saldo" data-estado={diferencia === 0 || ((amortizar || restoComo === 'saldo') && diferencia > 0) ? 'ok' : 'falta'} aria-live="polite">
            {restoComo === 'saldo'
              ? diferencia === 0
                ? 'Se reembolsa todo'
                : diferencia > 0
                  ? `El resto (${dinero(diferencia, moneda)}) quedará como saldo a favor`
                  : `Sobra ${dinero(-diferencia, moneda)}`
              : diferencia === 0
              ? amortizar
                ? 'Pagando la deuda completa'
                : 'Pago completo'
              : diferencia > 0
                ? amortizar
                  ? `Quedará pendiente ${dinero(diferencia, moneda)}`
                  : `Falta ${dinero(diferencia, moneda)}`
                : `Sobra ${dinero(-diferencia, moneda)}`}
          </span>
        )}
      </div>
    </div>
  )
}
