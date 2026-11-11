import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import Interruptor from '../../../shared/components/Interruptor'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { cuerpoDeZona, MAX_TRAMOS, MODALIDADES, revisarZona, zonaDesdeServidor, zonaVacia } from '../envios'
import LugaresZona from './LugaresZona'

const CLAVE = ['tienda', 'envios']

/** Crear o editar una zona de envío: nombre, forma de cobro, tarifas por peso y lugares. */
export default function ZonaModal({ zona, onCerrar }) {
  const [form, setForm] = useState(() => (zona ? zonaDesdeServidor(zona) : zonaVacia()))
  const [errores, setErrores] = useState({})
  const esTienda = form.modalidad === 'TIENDA'

  const cambiar = (campo, valor) => {
    setForm((f) => ({ ...f, [campo]: valor }))
    setErrores((e) => ({ ...e, [campo]: undefined }))
  }
  const cambiarTramo = (i, campo, valor) => cambiar('tarifas', form.tarifas.map((t, k) => (k === i ? { ...t, [campo]: valor } : t)))

  const guardar = useMutacion({
    mutationFn: (cuerpo) =>
      (form.id ? api.patch(`/tienda/admin/envios/zonas/${form.id}/`, cuerpo) : api.post('/tienda/admin/envios/zonas/', cuerpo)).then((r) => r.data),
    invalidar: [CLAVE],
    exito: form.id ? 'Zona actualizada.' : 'Zona creada.',
    alExito: onCerrar,
    avisarError: false,
  })

  const alGuardar = (evento) => {
    evento.preventDefault()
    const locales = revisarZona(form)
    setErrores(locales)
    if (Object.keys(locales).length > 0) return
    guardar.mutate(cuerpoDeZona(form), {
      onError: (error) => setErrores({ ...erroresDeCampo(error), _general: mensajeDeError(error) }),
    })
  }
  const otroError = errores._general && !Object.keys(errores).some((k) => k !== '_general' && errores[k])

  return (
    <Modal titulo={form.id ? 'Editar zona de envío' : 'Nueva zona de envío'} subtitulo="Dónde llegas y cuánto cuesta el envío." onCerrar={onCerrar} ancho={760}>
      <form onSubmit={alGuardar} noValidate className="envios-form">
        <div className="maestro-campos">
          <Campo etiqueta="Nombre de la zona" requerido error={errores.nombre} ayuda="Ej.: Lima, Provincias, Lima norte.">
            {(p) => <input {...p} name="nombre" value={form.nombre} maxLength={80} onChange={(e) => cambiar('nombre', e.target.value)} />}
          </Campo>
          <Campo etiqueta="¿Cómo se cobra?" tipo="select" error={errores.modalidad} ayuda={MODALIDADES[form.modalidad].ayuda}>
            {(p) => (
              <select {...p} name="modalidad" value={form.modalidad} onChange={(e) => cambiar('modalidad', e.target.value)}>
                {Object.entries(MODALIDADES).map(([valor, m]) => (
                  <option key={valor} value={valor}>
                    {m.texto}
                  </option>
                ))}
              </select>
            )}
          </Campo>
          <Campo etiqueta="Plazo de entrega" error={errores.plazo} ayuda="Ej.: 24 a 48 horas, 3 a 5 días.">
            {(p) => <input {...p} name="plazo" value={form.plazo} maxLength={100} onChange={(e) => cambiar('plazo', e.target.value)} />}
          </Campo>
          <Campo
            etiqueta="Detalle para el cliente"
            error={errores.detalle}
            ayuda={esTienda ? 'Ej.: Entregamos con nuestro reparto, de lunes a sábado.' : 'Ej.: Enviamos por Olva o Shalom, tú eliges la agencia.'}
          >
            {(p) => <input {...p} name="detalle" value={form.detalle} maxLength={250} onChange={(e) => cambiar('detalle', e.target.value)} />}
          </Campo>
        </div>

        {esTienda && (
          <fieldset className="envios-tarifas">
            <legend>Costo según el peso del pedido</legend>
            <p className="campo-ayuda">Se usa el primer tramo que alcance. Ej.: hasta 2 kg S/ 10, hasta 5 kg S/ 15.</p>
            <table>
              <thead>
                <tr>
                  <th scope="col">Hasta (kg)</th>
                  <th scope="col">Cuesta (S/)</th>
                  <th scope="col">
                    <span className="sr-only">Quitar</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {form.tarifas.map((t, i) => (
                  <tr key={i}>
                    <td>
                      <input aria-label={`Tramo ${i + 1}: hasta cuántos kg`} inputMode="decimal" value={t.hasta_kg} maxLength={9} onChange={(e) => cambiarTramo(i, 'hasta_kg', e.target.value)} />
                    </td>
                    <td>
                      <input aria-label={`Tramo ${i + 1}: costo en soles`} inputMode="decimal" value={t.costo} maxLength={11} onChange={(e) => cambiarTramo(i, 'costo', e.target.value)} />
                    </td>
                    <td>
                      <button
                        type="button"
                        className="icono-boton"
                        aria-label={`Quitar el tramo ${i + 1}`}
                        disabled={form.tarifas.length === 1}
                        onClick={() => cambiar('tarifas', form.tarifas.filter((_, k) => k !== i))}
                      >
                        <Icono nombre="papelera" tam={18} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <button type="button" disabled={form.tarifas.length >= MAX_TRAMOS} onClick={() => cambiar('tarifas', [...form.tarifas, { hasta_kg: '', costo: '' }])}>
              <Icono nombre="agregar" tam={16} /> Agregar tramo
            </button>
            {errores.tarifas && (
              <p role="alert" className="campo-error">
                {errores.tarifas}
              </p>
            )}
            <div className="maestro-campos">
              <Campo etiqueta="Por cada kg adicional (S/)" error={errores.kg_adicional} ayuda="Se suma por cada kg sobre el último tramo. Vacío = no se envían pedidos más pesados.">
                {(p) => <input {...p} name="kg_adicional" inputMode="decimal" value={form.kg_adicional} maxLength={11} onChange={(e) => cambiar('kg_adicional', e.target.value)} />}
              </Campo>
              <Campo etiqueta="Envío gratis desde (S/)" error={errores.envio_gratis_desde} ayuda="Compras desde este monto no pagan envío. Vacío = nunca.">
                {(p) => <input {...p} name="envio_gratis_desde" inputMode="decimal" value={form.envio_gratis_desde} maxLength={11} onChange={(e) => cambiar('envio_gratis_desde', e.target.value)} />}
              </Campo>
            </div>
          </fieldset>
        )}

        <LugaresZona lugares={form.coberturas} onCambio={(v) => cambiar('coberturas', v)} error={errores.coberturas} />

        <Interruptor
          activo={form.activa}
          onCambio={(v) => cambiar('activa', v)}
          texto={form.activa ? 'Zona activa' : 'Zona apagada'}
          descripcion={form.activa ? 'Los clientes de estos lugares pueden pedir envío.' : 'Los clientes de estos lugares no verán envío a domicilio.'}
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
            {guardar.isPending ? 'Guardando…' : 'Guardar zona'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
