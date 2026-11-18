import { useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import ImagenProtegida from '../../almacen/components/ImagenProtegida'
import { fechaHora, soles } from '../pedidos'

/** La foto del comprobante: el servidor la entrega solo con sesión (no tiene dirección pública). */
function FotoVoucher({ numero, subidoEn }) {
  const url = `/tienda/admin/pedidos/${numero}/voucher/?v=${encodeURIComponent(subidoEn ?? '')}`
  return <ImagenProtegida url={url} alt={`Comprobante de transferencia del pedido ${numero}`} className="voucher-imagen" />
}

/** Pedido pagado por transferencia: se ve el comprobante y se confirma o se rechaza el pago. */
export default function VerificarTransferencia({ pedido: p, numero, invalidar, puedeGestionar }) {
  const t = p.transferencia
  const [referencia, setReferencia] = useState(t?.operacion ?? '')
  const [motivo, setMotivo] = useState('')
  const [rechazando, setRechazando] = useState(false)
  const [error, setError] = useState('')

  const confirmar = useMutacion({
    mutationFn: () => api.post(`/tienda/admin/pedidos/${numero}/transferencia/confirmar/`, { referencia: referencia.trim() }).then((r) => r.data),
    invalidar,
    exito: 'Pago confirmado. Se emitió la venta y el dinero entró a la cuenta.',
    avisarError: false,
    alExito: () => setError(''),
  })
  const rechazar = useMutacion({
    mutationFn: () => api.post(`/tienda/admin/pedidos/${numero}/transferencia/rechazar/`, { motivo: motivo.trim() }).then((r) => r.data),
    invalidar,
    exito: 'Comprobante rechazado. Se avisó al cliente para que suba otro.',
    avisarError: false,
    alExito: () => {
      setError('')
      setRechazando(false)
      setMotivo('')
    },
  })
  const alError = { onError: (e) => setError(mensajeDeError(e)) }
  const cuenta = t?.cuenta
  const porVerificar = p.estado === 'POR_VERIFICAR'

  return (
    <section className="pedido-adelanto" aria-label="Pago por transferencia">
      <h3>Pago por transferencia o depósito</h3>
      <dl className="pedido-datos">
        <div className="pedido-dato">
          <dt>Monto a verificar</dt>
          <dd>
            <b>{soles(p.importes.total)}</b>
          </dd>
        </div>
        {cuenta && (
          <div className="pedido-dato">
            <dt>Cuenta elegida</dt>
            <dd>
              {cuenta.banco ? `${cuenta.banco} · ` : ''}
              {cuenta.nombre}
              <span className="sub-texto">
                {cuenta.titular} · {cuenta.numero}
              </span>
            </dd>
          </div>
        )}
        {t?.subido_en && (
          <div className="pedido-dato">
            <dt>Comprobante subido</dt>
            <dd>{fechaHora(t.subido_en)}</dd>
          </div>
        )}
        {t?.operacion && (
          <div className="pedido-dato">
            <dt>N.º de operación (del cliente)</dt>
            <dd>{t.operacion}</dd>
          </div>
        )}
        {!porVerificar && (
          <div className="pedido-dato">
            <dt>Puede pagar hasta</dt>
            <dd>{fechaHora(p.expira_en)}</dd>
          </div>
        )}
        {!porVerificar && t?.rechazo && (
          <div className="pedido-dato">
            <dt>Último rechazo</dt>
            <dd>{t.rechazo}</dd>
          </div>
        )}
      </dl>
      {!porVerificar && <p className="sub-texto">Todavía no subió su comprobante. Si no paga a tiempo, el pedido vence y se suelta el stock.</p>}

      {porVerificar && t?.tiene_voucher && <FotoVoucher numero={numero} subidoEn={t.subido_en} />}

      {error && (
        <p role="alert" className="campo-error">
          {error}
        </p>
      )}

      {porVerificar && puedeGestionar && !rechazando && (
        <>
          <p className="sub-texto">Revisa en tu banco que el dinero llegó, por el monto exacto, y recién confirma. Al confirmar se emite la venta y el pedido pasa a «Pagado».</p>
          <Campo etiqueta="N.º de operación del banco (opcional)">
            {(c) => <input {...c} name="referencia" value={referencia} maxLength={40} onChange={(e) => setReferencia(e.target.value)} />}
          </Campo>
          <div className="pagos-pie">
            <button type="button" className="primario" disabled={confirmar.isPending} onClick={() => confirmar.mutate(undefined, alError)}>
              {confirmar.isPending ? 'Confirmando…' : 'Confirmar que el dinero llegó'}
            </button>
            <button type="button" disabled={confirmar.isPending} onClick={() => setRechazando(true)}>
              Rechazar el comprobante…
            </button>
          </div>
        </>
      )}

      {porVerificar && puedeGestionar && rechazando && (
        <>
          <Campo etiqueta="¿Por qué se rechaza? (lo lee el cliente)" ayuda="Ej.: «El monto transferido no coincide con el total del pedido».">
            {(c) => <textarea {...c} name="motivo" rows={3} maxLength={250} value={motivo} onChange={(e) => setMotivo(e.target.value)} />}
          </Campo>
          <div className="pagos-pie">
            <button type="button" className="primario" disabled={rechazar.isPending || motivo.trim().length < 5} onClick={() => rechazar.mutate(undefined, alError)}>
              {rechazar.isPending ? 'Rechazando…' : 'Rechazar y avisar al cliente'}
            </button>
            <button type="button" disabled={rechazar.isPending} onClick={() => setRechazando(false)}>
              Volver
            </button>
          </div>
        </>
      )}
    </section>
  )
}
