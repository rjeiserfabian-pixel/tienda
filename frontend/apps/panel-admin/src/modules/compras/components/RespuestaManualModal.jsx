import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { cantidad as formatoCantidad } from '../../almacen/inventario'
import { armarCuerpoRespuesta, borradorRespuesta, validarRespuesta } from '../cotizaciones'

const SIN_ERRORES = {}

/** Registrar a mano lo que contestó un proveedor: condiciones y el precio de cada producto. */
export default function RespuestaManualModal({ cotizacion, respuesta, nombreProveedor, onCerrar }) {
  const [r, setR] = useState(() => borradorRespuesta(cotizacion, respuesta))
  const [intento, setIntento] = useState(false)
  const [general, setGeneral] = useState('')
  const lineas = cotizacion.lineas
  const validacion = validarRespuesta(r, lineas, cotizacion.fecha)
  const mostrar = intento ? validacion : { campos: SIN_ERRORES, porFila: SIN_ERRORES, faltan: [] }

  const guardar = useMutacion({
    mutationFn: (cuerpo) => api.post(`/compras/cotizaciones/${cotizacion.id}/respuesta/`, cuerpo, { timeout: 30_000 }).then((x) => x.data),
    invalidar: [['compras']],
    exito: `Respuesta de ${nombreProveedor} guardada.`,
    alExito: onCerrar,
    avisarError: false,
  })

  const poner = (campo) => (e) => setR((previa) => ({ ...previa, [campo]: e.target.value }))
  const ponerFila = (i, campo, valor) => setR((previa) => ({ ...previa, filas: previa.filas.map((f, j) => (j === i ? { ...f, [campo]: valor } : f)) }))

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending) return
    setIntento(true)
    setGeneral('')
    if (!validacion.valido) return
    guardar.mutate(armarCuerpoRespuesta(r, respuesta), {
      onError: (error) => {
        const campos = erroresDeCampo(error)
        setGeneral(Object.values(campos).join(' ') || mensajeDeError(error))
      },
    })
  }

  return (
    <Modal titulo="Registrar respuesta" subtitulo={`${cotizacion.codigo} · ${nombreProveedor}`} onCerrar={onCerrar} ancho={900}>
      <form onSubmit={enviar} noValidate>
        <p className="celda-suave">
          Precios en {cotizacion.moneda === 'USD' ? 'dólares' : 'soles'}, {cotizacion.precios_incluyen_igv ? 'con IGV incluido' : 'sin IGV'}. Deja vacío el precio de lo que el proveedor no cotiza.
        </p>
        <div className="fila-campos">
          <Campo etiqueta="Forma de pago" tipo="select">
            {(p) => (
              <select {...p} value={r.formaPago} disabled={guardar.isPending} onChange={poner('formaPago')}>
                <option value="CONTADO">Contado</option>
                <option value="CREDITO">Crédito</option>
              </select>
            )}
          </Campo>
          {r.formaPago === 'CREDITO' && (
            <Campo etiqueta="Plazo de crédito (días)" requerido error={mostrar.campos.plazoDias}>
              {(p) => <input {...p} inputMode="numeric" maxLength={3} value={r.plazoDias} disabled={guardar.isPending} onChange={(e) => setR((previa) => ({ ...previa, plazoDias: e.target.value.replace(/\D/g, '') }))} />}
            </Campo>
          )}
          <Campo etiqueta="Entrega en (días)" error={mostrar.campos.plazoEntrega} ayuda="Opcional.">
            {(p) => <input {...p} inputMode="numeric" maxLength={3} value={r.plazoEntrega} disabled={guardar.isPending} onChange={(e) => setR((previa) => ({ ...previa, plazoEntrega: e.target.value.replace(/\D/g, '') }))} />}
          </Campo>
          <Campo etiqueta="Precios válidos hasta" icono="calendario" error={mostrar.campos.validezHasta} ayuda="Opcional.">
            {(p) => <input {...p} type="date" min={cotizacion.fecha} value={r.validezHasta} disabled={guardar.isPending} onChange={poner('validezHasta')} />}
          </Campo>
        </div>

        <div className="marco-tabla compra-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th className="centrado">#</th>
                <th>Producto</th>
                <th className="num">Pedido</th>
                <th className="num">Precio unitario</th>
                <th className="num">Ofrece (opcional)</th>
                <th>Nota</th>
              </tr>
            </thead>
            <tbody>
              {lineas.map((l, i) => {
                const f = r.filas[i]
                const e = mostrar.porFila[f.linea]
                return (
                  <tr key={l.id}>
                    <td className="centrado celda-suave">{l.posicion}</td>
                    <td className="col-texto">
                      {l.producto_nombre}
                      <span className="sub-texto">{l.producto_codigo}</span>
                    </td>
                    <td className="num">
                      {formatoCantidad(l.cantidad)} {l.unidad}
                    </td>
                    <td className="num">
                      <input aria-label={`Precio de ${l.producto_nombre}`} className="compra-numero" inputMode="decimal" placeholder="No cotiza" value={f.precio} disabled={guardar.isPending} aria-invalid={Boolean(e?.precio)} onChange={(ev) => ponerFila(i, 'precio', ev.target.value)} />
                      {e?.precio && (
                        <small role="alert" className="campo-error">
                          {e.precio}
                        </small>
                      )}
                    </td>
                    <td className="num">
                      <input aria-label={`Cantidad que ofrece de ${l.producto_nombre}`} className="compra-numero" inputMode="decimal" placeholder="Todo" value={f.ofrecida} disabled={guardar.isPending} aria-invalid={Boolean(e?.ofrecida)} onChange={(ev) => ponerFila(i, 'ofrecida', ev.target.value)} />
                      {e?.ofrecida && (
                        <small role="alert" className="campo-error">
                          {e.ofrecida}
                        </small>
                      )}
                    </td>
                    <td>
                      <input aria-label={`Nota sobre ${l.producto_nombre}`} maxLength={120} value={f.observacion} disabled={guardar.isPending} onChange={(ev) => ponerFila(i, 'observacion', ev.target.value)} />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        <Campo etiqueta="Observación general" contador={{ actual: r.observacion.length, max: 250 }}>
          {(p) => <textarea {...p} rows={2} maxLength={250} placeholder="Opcional" value={r.observacion} disabled={guardar.isPending} onChange={poner('observacion')} />}
        </Campo>

        {intento && mostrar.faltan.length > 0 && (
          <ul className="compra-faltan" aria-live="polite">
            {mostrar.faltan.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        )}
        {general && (
          <p role="alert" className="campo-error">
            {general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={guardar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={guardar.isPending}>
            {guardar.isPending ? 'Guardando…' : 'Guardar respuesta'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
