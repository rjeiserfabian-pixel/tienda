import { useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Modal from '../../../shared/components/Modal'
import { fechaCorta } from '../../almacen/inventario'
import { aNumero } from '../../almacen/utilidades'
import { dinero, MONEDAS, numeroInterno } from '../compras'
import FormularioPago from './FormularioPago'


const deudaDe = (compra) => compra.cuotas.reduce((s, c) => s + Math.round(aNumero(c.saldo) * 100), 0) / 100

/** Resumen de la deuda: cuánto se compró, cuánto se pagó y cuánto falta, y en qué moneda. */
function Cabecera({ compra }) {
  const deuda = deudaDe(compra)
  const pagado = compra.cuotas.reduce((s, c) => s + Math.round(aNumero(c.pagado) * 100), 0) / 100
  const rebajado = Math.max(0, Math.round((Number(compra.total) - pagado - deuda) * 100) / 100)
  return (
    <>
      <dl className="datos-lista">
        <dt>Proveedor</dt>
        <dd>{compra.proveedor_nombre}</dd>
        <dt>Comprobante</dt>
        <dd>
          {compra.tipo_comprobante_nombre} {compra.comprobante} · emitido el {fechaCorta(compra.fecha_emision)}
        </dd>
        <dt>Moneda</dt>
        <dd>
          {compra.moneda === 'USD' ? 'Dólares americanos' : (MONEDAS[compra.moneda]?.nombre ?? compra.moneda)}
          {compra.moneda === 'USD' ? ` (tipo de cambio ${compra.tipo_cambio})` : ''}
        </dd>
      </dl>
      <dl className="cxp-tarjetas" aria-label="Estado de la deuda">
        <div>
          <dt>Total de la compra</dt>
          <dd>{dinero(compra.total, compra.moneda)}</dd>
        </div>
        <div>
          <dt>Pagado</dt>
          <dd>{dinero(pagado, compra.moneda)}</dd>
        </div>
        {rebajado > 0 && (
          <div>
            <dt>Rebajado por devoluciones</dt>
            <dd>{dinero(rebajado, compra.moneda)}</dd>
          </div>
        )}
        <div data-tono={deuda > 0 ? 'ambar' : undefined}>
          <dt>Deuda</dt>
          <dd>{dinero(deuda, compra.moneda)}</dd>
        </div>
      </dl>
    </>
  )
}

/**
 * Pagar una compra a crédito (amortizar): la deuda y cómo pagarla con uno o varios medios. El
 * detalle de la compra y sus pagos están en su ficha. La moneda decide qué cajas y cuentas se ofrecen.
 */
export default function PagarCompraModal({ compraId, cuotasIniciales, onCerrar }) {
  const consulta = useQuery({
    queryKey: ['compras', 'detalle', compraId],
    queryFn: ({ signal }) => api.get(`/compras/${compraId}/`, { signal }).then((r) => r.data),
    staleTime: 0,
  })
  const compra = consulta.data

  return (
    <Modal titulo="Pagar compra" subtitulo={compra ? `N° ${numeroInterno(compra)} · ${compra.comprobante}` : undefined} onCerrar={onCerrar} ancho={900}>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(compra)}>
        {compra && (
          <>
            <Cabecera compra={compra} />
            {deudaDe(compra) > 0 ? (
              <FormularioPago key={compra.cuotas.map((c) => c.pagado).join()} compra={compra} cuotasIniciales={cuotasIniciales} onCerrar={onCerrar} />
            ) : (
              <>
                <p className="estado-vacio">Esta compra ya está pagada por completo.</p>
                <div className="modal-pie">
                  <button type="button" onClick={onCerrar}>
                    Cerrar
                  </button>
                </div>
              </>
            )}
          </>
        )}
      </EstadoConsulta>
    </Modal>
  )
}
