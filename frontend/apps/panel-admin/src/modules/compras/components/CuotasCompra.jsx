import { fechaCorta } from '../../almacen/inventario'
import { aNumero } from '../../almacen/utilidades'
import { dinero, estadoCuota } from '../compras'

/**
 * Las cuotas de una compra a crédito, con cuánto se pagó de cada una (una cuota puede pagarse en
 * partes). Con permiso de pagar, se marcan las cuotas que se van a pagar y el botón de abajo abre
 * el pago ya con la suma de las marcadas.
 */
export default function CuotasCompra({ compra, seleccionables = false, marcadas = [], onMarcar, onPagar }) {
  const pendientes = compra.cuotas.filter((c) => aNumero(c.saldo) > 0)
  const marcadasPendientes = pendientes.filter((c) => marcadas.includes(c.id))
  const suma = marcadasPendientes.reduce((s, c) => s + Math.round(aNumero(c.saldo) * 100), 0) / 100
  const todas = pendientes.length > 0 && marcadasPendientes.length === pendientes.length
  const alternar = (id) => onMarcar(marcadas.includes(id) ? marcadas.filter((x) => x !== id) : [...marcadas, id])

  return (
    <>
      <div className="marco-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              {seleccionables && (
                <th className="centrado">
                  <input type="checkbox" aria-label="Marcar todas las cuotas pendientes" checked={todas} onChange={() => onMarcar(todas ? [] : pendientes.map((c) => c.id))} />
                </th>
              )}
              <th className="centrado">Cuota</th>
              <th>Vence</th>
              <th className="num">Monto</th>
              <th className="num">Pagado</th>
              <th className="num">Saldo</th>
              <th>Estado</th>
            </tr>
          </thead>
          <tbody>
            {compra.cuotas.map((c) => {
              const estado = estadoCuota(c, compra.estado === 'ANULADO')
              const pendiente = aNumero(c.saldo) > 0
              return (
                <tr key={c.id} className={seleccionables && marcadas.includes(c.id) ? 'compra-cuota-marcada' : undefined}>
                  {seleccionables && (
                    <td className="centrado">
                      <input type="checkbox" aria-label={`Marcar la cuota ${c.numero}`} disabled={!pendiente} checked={marcadas.includes(c.id)} onChange={() => alternar(c.id)} />
                    </td>
                  )}
                  <td className="centrado">{c.numero}</td>
                  <td>{fechaCorta(c.fecha_vencimiento)}</td>
                  <td className="num">{dinero(c.monto, compra.moneda)}</td>
                  <td className="num">{dinero(c.pagado, compra.moneda)}</td>
                  <td className="num">{dinero(c.saldo, compra.moneda)}</td>
                  <td className="cxp-vence">
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
      {seleccionables && (
        <div className="compra-pagar-marcadas" aria-live="polite">
          <span className="celda-suave">
            {marcadasPendientes.length === 0
              ? 'Marca las cuotas que vas a pagar (la casilla del encabezado marca todas las pendientes).'
              : `${marcadasPendientes.length} ${marcadasPendientes.length === 1 ? 'cuota marcada' : 'cuotas marcadas'}: ${dinero(suma, compra.moneda)}`}
          </span>
          <button type="button" className="primario" disabled={marcadasPendientes.length === 0} onClick={onPagar}>
            Pagar las marcadas
          </button>
        </div>
      )}
    </>
  )
}
