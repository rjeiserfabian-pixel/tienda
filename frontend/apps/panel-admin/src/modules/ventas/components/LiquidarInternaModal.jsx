import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { fechaCorta } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'

const SELECT_CUENTA = (cuentas) =>
  cuentas.map((c) => (
    <option key={c.id} value={c.id}>
      {c.nombre} · saldo {dinero(c.saldo, 'PEN')}
    </option>
  ))

/**
 * Liquida lo que se deben las dos empresas por sus ventas internas: una transferencia entre sus
 * cajas o cuentas. Las cuentas vienen propuestas (las cajas del mostrador) y se pueden cambiar,
 * por ejemplo si el cliente pagó con Yape y la caja no tiene efectivo.
 */
export default function LiquidarInternaModal({ pendiente: p, empresaId, onCerrar }) {
  const sinPago = Number(p.monto) === 0
  const [origen, setOrigen] = useState(String(p.cuenta_origen?.id ?? ''))
  const [destino, setDestino] = useState(String(p.cuenta_destino?.id ?? ''))
  const [referencia, setReferencia] = useState('')
  const [observacion, setObservacion] = useState('')
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')

  const cuerpo = {
    pagadora: p.pagadora,
    receptora: p.receptora,
    local: p.local,
    ...(!sinPago && origen ? { cuenta_origen: Number(origen) } : {}),
    ...(!sinPago && destino ? { cuenta_destino: Number(destino) } : {}),
    ...(referencia.trim() ? { referencia: referencia.trim() } : {}),
    ...(observacion.trim() ? { observacion: observacion.trim() } : {}),
  }
  const clave = useClaveIdempotente(cuerpo)
  const liquidar = useMutacion({
    mutationFn: ({ datos, llave }) => api.post('/ventas/liquidaciones-internas/', datos, { params: { empresa: empresaId }, headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['ventas'], ['caja']],
    exito: (l) => `Liquidación N° ${String(l.numero).padStart(6, '0')} registrada.`,
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (liquidar.isPending) return
    const e = {}
    if (!sinPago && !origen) e.origen = `Elige la caja o cuenta de ${p.pagadora_nombre}.`
    if (!sinPago && !destino) e.destino = `Elige la caja o cuenta de ${p.receptora_nombre}.`
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return
    liquidar.mutate({ datos: cuerpo, llave: clave }, {
      onError: (error) => {
        const campos = erroresDeCampo(error)
        setErrores({ origen: campos.cuenta_origen, destino: campos.cuenta_destino })
        setGeneral(Object.keys(campos).length ? 'Revisa los datos marcados.' : mensajeDeError(error))
      },
    })
  }

  return (
    <Modal titulo="Liquidar entre empresas" subtitulo={sinPago ? 'Las deudas se compensan: no hay dinero que mover' : `${p.pagadora_nombre} paga ${dinero(p.monto, 'PEN')} a ${p.receptora_nombre}`} onCerrar={onCerrar} ancho={680}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={liquidar.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
          {p.origen === 'COBRO_TIENDA' ? (
            <p className="celda-suave">
              {p.pagadora_nombre} cobró con Culqi pedidos de la tienda que incluían productos de {p.receptora_nombre}: le debe {dinero(p.debe_pagadora, 'PEN')} y {p.receptora_nombre} le debe {dinero(p.debe_receptora, 'PEN')}. Se compensan y queda{sinPago ? ' en cero' : `: ${dinero(p.monto, 'PEN')}`}. Al liquidar, la cuenta «Culqi (cobrado por otra empresa)» de {p.receptora_nombre} queda en cero y el dinero sale de la cuenta que elijas hacia el banco de {p.receptora_nombre}.
            </p>
          ) : (
          <p className="celda-suave">
            {p.pagadora_nombre} debe {dinero(p.debe_pagadora, 'PEN')} por mercadería de {p.receptora_nombre} y {p.receptora_nombre} debe {dinero(p.debe_receptora, 'PEN')}. Se compensan y queda{sinPago ? ' en cero' : `: ${dinero(p.monto, 'PEN')}`}. Es un asiento entre las cajas de las dos empresas: el efectivo no se mueve del cajón.
          </p>
          )}
          <div className="marco-tabla">
            <table className="tabla-datos">
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>Qué pasó</th>
                  <th>Origen</th>
                  <th>Debe</th>
                  <th className="num">Monto</th>
                </tr>
              </thead>
              <tbody>
                {p.partidas.map((x) => (
                  <tr key={x.id}>
                    <td>{fechaCorta(x.fecha)}</td>
                    <td>{x.motivo_nombre}</td>
                    <td className="celda-suave">{x.referencia}</td>
                    <td>
                      {x.deudora} → {x.acreedora}
                    </td>
                    <td className="num">{dinero(x.monto, 'PEN')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!sinPago && (
            <div className="fila-campos">
              <Campo etiqueta={`Sale de (${p.pagadora_nombre})`} tipo="select" requerido error={errores.origen} ayuda={p.motivo_cuentas || undefined}>
                {(c) => (
                  <select {...c} value={origen} onChange={(e) => setOrigen(e.target.value)}>
                    <option value="">Elige la caja o cuenta</option>
                    {SELECT_CUENTA(p.cuentas_pagadora)}
                  </select>
                )}
              </Campo>
              <Campo etiqueta={`Entra a (${p.receptora_nombre})`} tipo="select" requerido error={errores.destino}>
                {(c) => (
                  <select {...c} value={destino} onChange={(e) => setDestino(e.target.value)}>
                    <option value="">Elige la caja o cuenta</option>
                    {SELECT_CUENTA(p.cuentas_receptora)}
                  </select>
                )}
              </Campo>
            </div>
          )}
          <div className="fila-campos">
            <Campo etiqueta="Referencia" ayuda="Opcional.">
              {(c) => <input {...c} maxLength={60} value={referencia} onChange={(e) => setReferencia(e.target.value)} />}
            </Campo>
            <Campo etiqueta="Observación" contador={{ actual: observacion.length, max: 250 }}>
              {(c) => <input {...c} maxLength={250} placeholder="Opcional" value={observacion} onChange={(e) => setObservacion(e.target.value)} />}
            </Campo>
          </div>
        </fieldset>
        {general && (
          <p role="alert" className="campo-error">
            {general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={liquidar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={liquidar.isPending}>
            {liquidar.isPending ? 'Liquidando…' : sinPago ? 'Cerrar cuentas' : 'Liquidar'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
