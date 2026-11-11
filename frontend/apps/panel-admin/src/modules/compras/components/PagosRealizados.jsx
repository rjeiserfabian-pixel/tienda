import { useState } from 'react'
import Can from '../../../shared/components/Can'
import { Icono } from '../../../shared/components/IconosPanel'
import { fechaCorta } from '../../almacen/inventario'
import { dinero } from '../compras'
import AnularPagoModal from './AnularPagoModal'

/** Qué cubrió un pago: a qué cuotas fue y cuánto a cada una (un pago puede cubrir una cuota solo en parte). */
const cuotasDe = (pago, compra) => {
  if (pago.tipo === 'FLETE') return 'Flete'
  if (pago.cuotas_pagadas.length === 0) return compra.forma_pago === 'CONTADO' ? 'Al registrar la compra' : '—'
  return pago.cuotas_pagadas.map((x) => `Cuota ${x.numero}: ${dinero(x.monto, compra.moneda)}`).join(' · ')
}

/**
 * Todos los pagos de la compra: fecha, método, caja o cuenta, a qué cuotas fueron y cuánto a cada
 * una. Un pago hecho después de registrar la compra, por error, se anula (con permiso) y la deuda vuelve.
 */
export default function PagosRealizados({ compra }) {
  const [anulando, setAnulando] = useState(null)
  if (compra.pagos.length === 0) return <p className="estado-vacio">Todavía no se hizo ningún pago a esta compra.</p>
  return (
    <>
      <div className="marco-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Método</th>
              <th>Caja o cuenta</th>
              <th>Aplicado a</th>
              <th className="num">Monto</th>
              <th className="centrado">
                <span className="sr-only">Acciones</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {compra.pagos.map((p) => (
              <tr key={p.id} className={p.anulado ? 'anulado' : undefined}>
                <td>{fechaCorta(p.fecha)}</td>
                <td>
                  {p.medio_pago_nombre}
                  {p.referencia && <span className="sub-texto">Operación {p.referencia}</span>}
                </td>
                <td>{p.cuenta_nombre}</td>
                <td className="celda-suave">{cuotasDe(p, compra)}</td>
                <td className="num">
                  {dinero(p.monto, p.tipo === 'FLETE' ? 'PEN' : compra.moneda)}
                  {p.tipo_cambio && <span className="sub-texto">Salió {dinero(p.monto_cuenta, p.moneda_cuenta)} de la cuenta (tipo de cambio {p.tipo_cambio})</span>}
                  {p.anulado && p.motivo_anulacion && <span className="sub-texto">Anulado: {p.motivo_anulacion}</span>}
                </td>
                <td className="centrado">
                  {!p.anulado && compra.estado === 'EMITIDO' && p.cuotas_pagadas.length > 0 && (
                    <Can permiso="COMPRAS.ANULAR">
                      <button type="button" className="accion-icono peligro-suave" aria-label={`Anular el pago del ${fechaCorta(p.fecha)}`} title="Anular este pago" onClick={() => setAnulando(p)}>
                        <Icono nombre="apagar" tam={19} />
                      </button>
                    </Can>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {anulando && <AnularPagoModal compra={compra} pago={anulando} onCerrar={() => setAnulando(null)} />}
    </>
  )
}
