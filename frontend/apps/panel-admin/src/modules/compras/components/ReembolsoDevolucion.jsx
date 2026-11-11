import { dinero } from '../compras'
import PagosContado from './PagosContado'

/**
 * Qué pasa con lo que ya estaba pagado: el proveedor devuelve el dinero (a una caja o cuenta) o
 * queda como saldo a favor para futuras compras. Lo que rebaja la deuda no entra aquí.
 */
export default function ReembolsoDevolucion({ aDeuda, porRecuperar, moneda, reembolsar, onReembolsar, resueltos, cuentas, medios, errores, sinPermisoCajas, onPagos, disabled }) {
  if (porRecuperar <= 0) {
    return (
      <p className="celda-suave" role="status">
        {aDeuda > 0 ? `Esta nota rebaja lo que todavía se debe (${dinero(aDeuda, moneda)}): no hay dinero que recuperar.` : 'Elige qué productos devuelves para ver qué pasa con el dinero.'}
      </p>
    )
  }
  return (
    <>
      {aDeuda > 0 && <p className="celda-suave">{dinero(aDeuda, moneda)} de la nota rebajan lo que aún se debe. Los otros {dinero(porRecuperar, moneda)} ya estaban pagados.</p>}
      <div className="segmentos" role="radiogroup" aria-label="Qué pasa con lo ya pagado">
        <button type="button" role="radio" aria-checked={!reembolsar} className={!reembolsar ? 'activo' : undefined} disabled={disabled} onClick={() => onReembolsar(false)}>
          Queda como saldo a favor
        </button>
        <button type="button" role="radio" aria-checked={reembolsar} className={reembolsar ? 'activo' : undefined} disabled={disabled} onClick={() => onReembolsar(true)}>
          El proveedor devuelve el dinero
        </button>
      </div>
      {!reembolsar ? (
        <p className="celda-suave">{dinero(porRecuperar, moneda)} quedarán como saldo a favor con este proveedor y se podrán usar para pagar otras compras a crédito.</p>
      ) : (
        <PagosContado
          resueltos={resueltos}
          cuentas={cuentas}
          medios={medios}
          moneda={moneda}
          total={porRecuperar}
          errores={errores}
          sinPermisoCajas={sinPermisoCajas}
          onPagos={onPagos}
          disabled={disabled}
          entra
          restoComo="saldo"
          amortizar
        />
      )}
    </>
  )
}
