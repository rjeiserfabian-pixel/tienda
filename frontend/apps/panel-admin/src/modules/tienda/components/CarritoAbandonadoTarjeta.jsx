import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Interruptor from '../../../shared/components/Interruptor'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { soles } from '../ofertas'

const CLAVE = ['tienda', 'carrito-abandonado']

/** Recordatorios por correo a quien dejó productos en su carrito: se encienden y se miden aquí. */
export default function CarritoAbandonadoTarjeta() {
  const consulta = useQuery({
    queryKey: CLAVE,
    queryFn: ({ signal }) => api.get('/tienda/admin/carrito-abandonado/', { signal }).then((r) => r.data),
    refetchOnWindowFocus: false,
  })
  const d = consulta.data
  const [form, setForm] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (d) setForm({ activo: d.activo, horas_primero: String(d.horas_primero), horas_segundo: String(d.horas_segundo), cupon: d.cupon ? String(d.cupon) : '' })
  }, [d])

  const guardar = useMutacion({
    mutationFn: (cuerpo) => api.patch('/tienda/admin/carrito-abandonado/', cuerpo).then((r) => r.data),
    invalidar: [CLAVE],
    exito: 'Recordatorios de carrito guardados.',
    avisarError: false,
  })

  if (!d || !form) return null

  const cambiado =
    form.activo !== d.activo || form.horas_primero !== String(d.horas_primero) || form.horas_segundo !== String(d.horas_segundo) || form.cupon !== (d.cupon ? String(d.cupon) : '')

  const enviar = (evento) => {
    evento.preventDefault()
    setError('')
    const h1 = Number(form.horas_primero)
    const h2 = Number(form.horas_segundo)
    if (!(Number.isInteger(h1) && h1 >= 1 && h1 <= 72)) return setError('El primer recordatorio va entre 1 y 72 horas.')
    if (!(Number.isInteger(h2) && h2 >= 1 && h2 <= 168)) return setError('El segundo recordatorio va entre 1 y 168 horas.')
    guardar.mutate(
      { activo: form.activo, horas_primero: h1, horas_segundo: h2, cupon: form.cupon ? Number(form.cupon) : null },
      { onError: (e) => setError(mensajeDeError(e)) },
    )
  }

  const e = d.estadisticas

  return (
    <PanelTarjeta
      id="carrito-abandonado"
      icono="cart"
      titulo="Carrito abandonado"
      descripcion="Un correo para quien dejó productos en su carrito. Solo a clientes con cuenta que aceptaron recibir ofertas, y cada correo trae un enlace para darse de baja."
    >
      <form onSubmit={enviar} noValidate className="envios-form">
        <Interruptor
          activo={form.activo}
          onCambio={(v) => setForm((f) => ({ ...f, activo: v }))}
          texto={form.activo ? 'Recordatorios activados' : 'Recordatorios desactivados'}
          descripcion={form.activo ? 'Se envían como máximo 2 por carrito.' : 'No se envía ningún recordatorio.'}
        />
        <div className="maestro-campos">
          <Campo etiqueta="Primer recordatorio (horas después de dejarlo)">
            {(p) => <input {...p} name="horas_primero" inputMode="numeric" value={form.horas_primero} onChange={(ev) => setForm((f) => ({ ...f, horas_primero: ev.target.value }))} />}
          </Campo>
          <Campo etiqueta="Segundo recordatorio (horas después del primero)">
            {(p) => <input {...p} name="horas_segundo" inputMode="numeric" value={form.horas_segundo} onChange={(ev) => setForm((f) => ({ ...f, horas_segundo: ev.target.value }))} />}
          </Campo>
          <Campo etiqueta="Cupón de incentivo (opcional)" ayuda="Se incluye en el segundo recordatorio. Crea antes el cupón en esta misma pantalla.">
            {(p) => (
              <select {...p} name="cupon" value={form.cupon} onChange={(ev) => setForm((f) => ({ ...f, cupon: ev.target.value }))}>
                <option value="">Sin cupón</option>
                {d.cupones.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.codigo}
                    {c.nombre ? ` · ${c.nombre}` : ''}
                  </option>
                ))}
              </select>
            )}
          </Campo>
        </div>
        {error && (
          <p role="alert" className="campo-error">
            {error}
          </p>
        )}
        <div className="pagos-pie">
          <button type="submit" className="primario" disabled={!cambiado || guardar.isPending}>
            {guardar.isPending ? 'Guardando…' : 'Guardar'}
          </button>
        </div>
      </form>
      <dl className="pedido-datos carrito-resultados" aria-label="Resultados de los recordatorios">
        <div className="pedido-dato">
          <dt>Recordatorios enviados</dt>
          <dd>{e.recordatorios}</dd>
        </div>
        <div className="pedido-dato">
          <dt>Clientes a los que se les recordó</dt>
          <dd>{e.clientes}</dd>
        </div>
        <div className="pedido-dato">
          <dt>Compraron después de un recordatorio</dt>
          <dd>{e.recuperados}</dd>
        </div>
        <div className="pedido-dato">
          <dt>Vendido gracias a los recordatorios</dt>
          <dd>{soles(e.vendido)}</dd>
        </div>
      </dl>
    </PanelTarjeta>
  )
}
