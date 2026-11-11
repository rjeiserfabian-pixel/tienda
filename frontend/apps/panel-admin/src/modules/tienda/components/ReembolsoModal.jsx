import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { MONTO_ALTO_REEMBOLSO, RUTAS_REEMBOLSO, soles } from '../pedidos'

/**
 * Reembolsar un pedido pagado. Primero explica EXACTAMENTE qué pasará (lo pide al servidor, que no
 * cambia nada al calcularlo), pide el motivo y, si el monto es alto, que se escriba el número del
 * pedido. Es dinero real: el servidor vuelve a verificar el permiso y cada paso.
 */
export default function ReembolsoModal({ numero, lineas = [], invalidar, onCerrar }) {
  const plan = useQuery({
    queryKey: ['tienda', 'pedido', numero, 'reembolso-plan'],
    queryFn: ({ signal }) => api.get(`/tienda/admin/pedidos/${numero}/reembolso/plan/`, { signal }).then((r) => r.data),
    refetchOnWindowFocus: false,
    gcTime: 0,
  })
  const d = plan.data

  const [motivoTipo, setMotivoTipo] = useState('SOLICITUD_CLIENTE')
  const [motivo, setMotivo] = useState('')
  const [parcial, setParcial] = useState(false)
  const [cantidades, setCantidades] = useState({}) // id de línea → cantidad a devolver
  const [volvioElEquipo, setVolvioElEquipo] = useState(true)
  const [confirmaNumero, setConfirmaNumero] = useState('')
  const [error, setError] = useState('')

  const lineasProductos = lineas.filter((l) => !l.es_envio)
  const elegidas = Object.entries(cantidades)
    .map(([linea, cantidad]) => ({ linea: Number(linea), cantidad: String(cantidad) }))
    .filter((x) => Number(x.cantidad) > 0)

  const reembolsar = useMutacion({
    mutationFn: () =>
      api
        .post(`/tienda/admin/pedidos/${numero}/reembolso/`, {
          motivo_tipo: motivoTipo,
          motivo: motivo.trim(),
          ...(d?.ruta === 'NOTA_CREDITO' ? { reingresa_stock: volvioElEquipo } : {}),
          ...(parcial ? { lineas: elegidas } : {}),
        })
        .then((r) => r.data),
    invalidar,
    avisarError: false,
    exito: (r) =>
      r.estado === 'REEMBOLSO_PENDIENTE'
        ? 'Quedó anulado en el sistema; Culqi aún no confirmó la devolución del dinero.'
        : 'Reembolso hecho: Culqi devolvió el dinero.',
    alExito: onCerrar,
  })

  const alto = Number(d?.monto ?? 0) >= MONTO_ALTO_REEMBOLSO
  const motivoOk = motivo.trim().length >= 3
  const parcialOk = !parcial || elegidas.length > 0
  const confirmaOk = !alto || confirmaNumero.trim().toUpperCase() === numero
  const listo = Boolean(d) && motivoOk && parcialOk && confirmaOk

  const enviar = (e) => {
    e.preventDefault()
    setError('')
    reembolsar.mutate(undefined, { onError: (err) => setError(mensajeDeError(err)) })
  }

  return (
    <Modal titulo={`Reembolsar el pedido ${numero}`} subtitulo="Dinero real: revisa bien antes de confirmar" onCerrar={onCerrar} ancho={620}>
      {plan.isLoading && <p aria-busy="true">Calculando qué pasará…</p>}
      {plan.isError && (
        <p role="alert" className="campo-error">
          {mensajeDeError(plan.error)}
        </p>
      )}
      {d && (
        <form onSubmit={enviar} noValidate className="reembolso-form">
          <section className="reembolso-plan" aria-label="Qué pasará">
            <h3>{RUTAS_REEMBOLSO[d.ruta]}</h3>
            <ol>
              {d.pasos.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ol>
            <p className="reembolso-monto">
              A devolver: <strong>{soles(d.monto)}</strong>
              {Number(d.ya_reembolsado) > 0 && (
                <span className="sub-texto">
                  {' '}
                  (ya se devolvieron {soles(d.ya_reembolsado)} de {soles(d.total)})
                </span>
              )}
            </p>
            {parcial && <p className="sub-texto">Con una devolución parcial, el monto es el de las unidades que elijas.</p>}
            {d.avisos.map((a) => (
              <p key={a} className="sub-texto">
                {a}
              </p>
            ))}
          </section>

          <Campo etiqueta="¿Por qué se reembolsa?" requerido tipo="select">
            {(p) => (
              <select {...p} value={motivoTipo} onChange={(e) => setMotivoTipo(e.target.value)}>
                {d.motivos.map((m) => (
                  <option key={m.valor} value={m.valor}>
                    {m.texto}
                  </option>
                ))}
              </select>
            )}
          </Campo>
          <Campo etiqueta="Explica el motivo" requerido contador={{ actual: motivo.length, max: 250 }} ayuda="Queda en el historial del pedido y en la auditoría.">
            {(p) => <input {...p} maxLength={250} value={motivo} placeholder="Ej.: el cliente pidió devolver el equipo" onChange={(e) => setMotivo(e.target.value)} />}
          </Campo>

          {d.ruta === 'NOTA_CREDITO' && (
            <>
              <label className="reembolso-check">
                <input type="checkbox" checked={volvioElEquipo} onChange={(e) => setVolvioElEquipo(e.target.checked)} />
                <span>El equipo ya regresó al almacén (vuelve al stock y a sus series)</span>
              </label>
              {d.permite_parcial && (
                <label className="reembolso-check">
                  <input type="checkbox" checked={parcial} onChange={(e) => setParcial(e.target.checked)} />
                  <span>Devolver solo una parte del pedido</span>
                </label>
              )}
              {parcial && (
                <div className="reembolso-lineas" aria-label="Qué se devuelve">
                  {lineasProductos.map((l) => (
                    <label key={l.id}>
                      <span>
                        {l.descripcion} <span className="sub-texto">(compró {l.cantidad})</span>
                      </span>
                      <input
                        type="number"
                        min="0"
                        max={l.cantidad}
                        step="1"
                        inputMode="numeric"
                        value={cantidades[l.id] ?? ''}
                        placeholder="0"
                        onChange={(e) => setCantidades((c) => ({ ...c, [l.id]: e.target.value }))}
                      />
                    </label>
                  ))}
                  <p className="sub-texto">El envío no se devuelve en una devolución parcial.</p>
                </div>
              )}
            </>
          )}

          {alto && (
            <Campo etiqueta={`Escribe ${numero} para confirmar`} requerido ayuda={`Es un reembolso grande (desde ${soles(MONTO_ALTO_REEMBOLSO)}).`}>
              {(p) => <input {...p} autoComplete="off" value={confirmaNumero} onChange={(e) => setConfirmaNumero(e.target.value)} />}
            </Campo>
          )}

          {error && (
            <p role="alert" className="campo-error">
              {error}
            </p>
          )}
          <div className="acciones">
            <button type="button" onClick={onCerrar} disabled={reembolsar.isPending}>
              Cancelar
            </button>
            <button type="submit" className="peligro" disabled={!listo || reembolsar.isPending}>
              {reembolsar.isPending ? 'Reembolsando…' : parcial ? 'Reembolsar lo elegido' : `Reembolsar ${soles(d.monto)}`}
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}
