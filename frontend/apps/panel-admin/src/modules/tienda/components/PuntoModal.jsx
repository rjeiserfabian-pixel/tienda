import { useMemo, useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Interruptor from '../../../shared/components/Interruptor'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { agruparAlmacenes } from '../configuracion'
import { cuerpoDePunto, puntoDesdeServidor, puntoVacio, revisarPunto } from '../envios'

const CLAVE = ['tienda', 'envios']

/** Crear o editar un punto de recojo y marcar los almacenes de ese local. */
export default function PuntoModal({ punto, almacenes, onCerrar }) {
  const [form, setForm] = useState(() => (punto ? puntoDesdeServidor(punto) : puntoVacio()))
  const [errores, setErrores] = useState({})
  const grupos = useMemo(() => agruparAlmacenes(almacenes), [almacenes])

  const cambiar = (campo, valor) => {
    setForm((f) => ({ ...f, [campo]: valor }))
    setErrores((e) => ({ ...e, [campo]: undefined }))
  }
  const alternar = (id) => cambiar('almacenes', form.almacenes.includes(id) ? form.almacenes.filter((x) => x !== id) : [...form.almacenes, id])

  const guardar = useMutacion({
    mutationFn: (cuerpo) =>
      (form.id ? api.patch(`/tienda/admin/envios/puntos/${form.id}/`, cuerpo) : api.post('/tienda/admin/envios/puntos/', cuerpo)).then((r) => r.data),
    invalidar: [CLAVE],
    exito: form.id ? 'Punto de recojo actualizado.' : 'Punto de recojo creado.',
    alExito: onCerrar,
    avisarError: false,
  })

  const alGuardar = (evento) => {
    evento.preventDefault()
    const locales = revisarPunto(form)
    setErrores(locales)
    if (Object.keys(locales).length > 0) return
    guardar.mutate(cuerpoDePunto(form), {
      onError: (error) => setErrores({ ...erroresDeCampo(error), _general: mensajeDeError(error) }),
    })
  }
  const otroError = errores._general && !Object.keys(errores).some((k) => k !== '_general' && errores[k])

  return (
    <Modal titulo={form.id ? 'Editar punto de recojo' : 'Nuevo punto de recojo'} subtitulo="Un local donde el cliente recoge su pedido." onCerrar={onCerrar} ancho={680}>
      <form onSubmit={alGuardar} noValidate className="envios-form">
        <div className="maestro-campos">
          <Campo etiqueta="Nombre del punto" requerido error={errores.nombre} ayuda="Ej.: Tienda Centro.">
            {(p) => <input {...p} name="nombre" value={form.nombre} maxLength={100} onChange={(e) => cambiar('nombre', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Dirección" requerido error={errores.direccion}>
            {(p) => <input {...p} name="direccion" value={form.direccion} maxLength={250} onChange={(e) => cambiar('direccion', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Horario" error={errores.horario} ayuda="Ej.: Lunes a sábado, 9 a. m. a 7 p. m.">
            {(p) => <input {...p} name="horario" value={form.horario} maxLength={200} onChange={(e) => cambiar('horario', e.target.value)} />}
          </Campo>
          <Campo etiqueta="¿Cuándo está listo?" error={errores.listo_en} ayuda="Ej.: Listo en 2 horas.">
            {(p) => <input {...p} name="listo_en" value={form.listo_en} maxLength={80} onChange={(e) => cambiar('listo_en', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Teléfono" error={errores.telefono}>
            {(p) => <input {...p} name="telefono" inputMode="tel" value={form.telefono} maxLength={20} onChange={(e) => cambiar('telefono', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Indicaciones" error={errores.indicaciones} ayuda="Ej.: Tocar el timbre del segundo piso; llevar DNI.">
            {(p) => <input {...p} name="indicaciones" value={form.indicaciones} maxLength={250} onChange={(e) => cambiar('indicaciones', e.target.value)} />}
          </Campo>
        </div>

        <fieldset className="envios-almacenes">
          <legend>Almacenes de este local</legend>
          <p className="campo-ayuda">
            El cliente solo verá este punto si TODO su pedido está en estos almacenes (y estos almacenes abastecen la tienda). Marca los de las
            dos empresas si comparten el local.
          </p>
          {grupos.length === 0 ? (
            <p className="celda-suave">No hay almacenes activos.</p>
          ) : (
            <div className="tienda-almacenes">
              {grupos.map((g) => (
                <fieldset key={g.empresa} className="tienda-almacenes-grupo">
                  <legend>{g.empresa}</legend>
                  <ul>
                    {g.almacenes.map((a) => (
                      <li key={a.id}>
                        <label className="tienda-casilla">
                          <input type="checkbox" checked={form.almacenes.includes(a.id)} onChange={() => alternar(a.id)} />
                          {a.nombre}
                        </label>
                      </li>
                    ))}
                  </ul>
                </fieldset>
              ))}
            </div>
          )}
          {errores.almacenes && (
            <p role="alert" className="campo-error">
              {errores.almacenes}
            </p>
          )}
          {form.almacenes.length === 0 && <p className="celda-suave">Sin almacenes marcados, este punto nunca tendrá stock.</p>}
        </fieldset>

        <Interruptor
          activo={form.activo}
          onCambio={(v) => cambiar('activo', v)}
          texto={form.activo ? 'Punto activo' : 'Punto apagado'}
          descripcion={form.activo ? 'Los clientes pueden elegirlo para recoger.' : 'No se ofrece a los clientes.'}
        />

        {otroError && (
          <p role="alert" className="campo-error">
            {errores._general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={guardar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={guardar.isPending}>
            {guardar.isPending ? 'Guardando…' : 'Guardar punto'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
