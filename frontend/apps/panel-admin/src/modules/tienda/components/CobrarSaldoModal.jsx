import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaHora, soles } from '../pedidos'

/** Al recoger un pedido con adelanto: cobra el saldo, emite el comprobante por el total y entrega. */
export default function CobrarSaldoModal({ numero, onCerrar, invalidar }) {
  const consulta = useQuery({
    queryKey: ['tienda', 'pedido-saldo', numero],
    queryFn: ({ signal }) => api.get(`/tienda/admin/pedidos/${numero}/saldo/`, { signal }).then((r) => r.data),
    refetchOnWindowFocus: false,
  })
  const datos = consulta.data
  const [medio, setMedio] = useState('')
  const [referencia, setReferencia] = useState('')
  const [error, setError] = useState('')

  const elegido = datos?.medios?.find((m) => String(m.id) === String(medio))

  const cobrar = useMutacion({
    mutationFn: (cuerpo) => api.post(`/tienda/admin/pedidos/${numero}/saldo/`, cuerpo).then((r) => r.data),
    invalidar,
    exito: 'Saldo cobrado. El pedido quedó entregado y el comprobante emitido.',
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    setError('')
    if (!medio) return setError('Elige con qué paga el cliente el saldo.')
    if (elegido?.requiere_referencia && !referencia.trim()) return setError(`Escribe el número de operación del pago con ${elegido.nombre}.`)
    cobrar.mutate(
      { medio_pago: Number(medio), referencia: referencia.trim() },
      { onError: (e) => setError(mensajeDeError(e)) },
    )
  }

  return (
    <Modal titulo="Cobrar el saldo y entregar" subtitulo={`Pedido ${numero}`} onCerrar={onCerrar} ancho={560}>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(datos)}>
        {datos && !datos.puede && <p className="celda-suave">Este pedido ya no admite cobrar un saldo.</p>}
        {datos?.puede && (
          <form onSubmit={enviar} noValidate className="envios-form">
            <dl className="pedido-datos">
              <div className="pedido-dato">
                <dt>Total del pedido</dt>
                <dd>{soles(datos.total)}</dd>
              </div>
              <div className="pedido-dato">
                <dt>Adelanto ya pagado</dt>
                <dd>{soles(datos.adelanto)}</dd>
              </div>
              <div className="pedido-dato">
                <dt>
                  <b>Saldo a cobrar ahora</b>
                </dt>
                <dd>
                  <b>{soles(datos.saldo)}</b>
                </dd>
              </div>
              {datos.vence_en && (
                <div className="pedido-dato">
                  <dt>Plazo para recoger</dt>
                  <dd>{fechaHora(datos.vence_en)}</dd>
                </div>
              )}
            </dl>
            <Campo etiqueta="¿Con qué paga el cliente el saldo?" requerido>
              {(p) => (
                <select {...p} name="medio_pago" value={medio} onChange={(e) => setMedio(e.target.value)}>
                  <option value="">Elige…</option>
                  {datos.medios.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.nombre}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            {elegido?.requiere_referencia && (
              <Campo etiqueta="Número de operación" requerido>
                {(p) => <input {...p} name="referencia" value={referencia} maxLength={60} onChange={(e) => setReferencia(e.target.value)} />}
              </Campo>
            )}
            <p className="celda-suave">Se emite el comprobante por el total ({soles(datos.total)}) y el adelanto se descuenta. Esto no se puede deshacer desde aquí.</p>
            {error && (
              <p role="alert" className="campo-error">
                {error}
              </p>
            )}
            <div className="modal-pie">
              <button type="button" onClick={onCerrar} disabled={cobrar.isPending}>
                Cancelar
              </button>
              <button type="submit" className="primario" disabled={cobrar.isPending}>
                {cobrar.isPending ? 'Cobrando…' : `Cobrar ${soles(datos.saldo)} y entregar`}
              </button>
            </div>
          </form>
        )}
      </EstadoConsulta>
    </Modal>
  )
}
