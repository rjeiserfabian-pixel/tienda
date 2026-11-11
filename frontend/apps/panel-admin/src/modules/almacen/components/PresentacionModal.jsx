import { useMemo, useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useOpciones } from '../hooks/useOpciones'
import { useCalculoPrecios } from '../../../shared/hooks/useCalculoPrecios'
import { aNumero, soles } from '../utilidades'

const desdeRegistro = (presentacion, listas) =>
  Object.fromEntries(
    listas.map((l) => {
      const fila = (presentacion?.precios ?? []).find((p) => p.lista === l.id)
      return [l.id, { precio: fila ? String(Number(fila.precio)) : '' }]
    }),
  )

/**
 * Alta o edición de una presentación (caja, docena…): su unidad, cuántas unidades base trae, su
 * código de barras y su precio en cada lista. El costo de la presentación es el costo base × el
 * factor: con él se calcula la utilidad o el margen (el servidor la vuelve a calcular).
 */
export default function PresentacionModal({ producto, presentacion, listas, puedePrecios, onCerrar }) {
  const nueva = !presentacion
  const calc = useCalculoPrecios()
  const [unidad, setUnidad] = useState('')
  const [factor, setFactor] = useState(presentacion ? String(Number(presentacion.factor)) : '')
  const [barras, setBarras] = useState(presentacion?.codigo_barras ?? '')
  const [precios, setPrecios] = useState(() => desdeRegistro(presentacion, listas))
  const [errores, setErrores] = useState({})

  const unidades = useOpciones('/mantenimiento/unidades/', {}, { enabled: nueva })
  const ocupadas = useMemo(() => new Set((producto.presentaciones ?? []).map((p) => p.unidad)), [producto.presentaciones])
  const elegibles = (unidades.data ?? []).filter((u) => u.id !== producto.unidad && !ocupadas.has(u.id))

  const factorNumero = aNumero(factor)
  const costoBase = aNumero(producto.costo)
  const costoPresentacion = factorNumero && costoBase ? costoBase * factorNumero : null
  const unidadElegida = nueva ? (unidades.data ?? []).find((u) => String(u.id) === unidad) : { nombre: presentacion.unidad_nombre }

  const guardar = useMutacion({
    mutationFn: (datos) =>
      nueva ? api.post('/mantenimiento/presentaciones/', datos).then((r) => r.data) : api.patch(`/mantenimiento/presentaciones/${presentacion.id}/`, datos).then((r) => r.data),
    invalidar: [['productos'], ['opciones']],
    exito: nueva ? 'Presentación agregada.' : 'Presentación actualizada.',
    alExito: onCerrar,
    avisarError: false,
  })

  // El precio es lo que se guarda; el porcentaje solo se guarda mientras se escribe (si no, se deriva).
  const ponerPrecio = (id, precio) => setPrecios((previo) => ({ ...previo, [id]: { precio } }))
  const ponerPorcentaje = (id, pct) =>
    setPrecios((previo) => ({ ...previo, [id]: { pct, precio: costoPresentacion ? calc.aPrecio(costoPresentacion, pct) : (previo[id]?.precio ?? '') } }))

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending) return
    const locales = {}
    if (nueva && !unidad) locales.unidad = 'Elija la unidad.'
    if (factorNumero === null || factorNumero <= 0 || factorNumero === 1) locales.factor = 'Cuántas unidades base trae (mayor que 0 y distinto de 1).'
    else if (!/^\d+([.,]\d{1,3})?$/.test(String(factor).trim())) locales.factor = 'Hasta 3 decimales.'
    for (const l of listas) {
      const p = aNumero(precios[l.id]?.precio)
      if (precios[l.id]?.precio !== '' && (p === null || p < 0)) locales.precios = `El precio de «${l.nombre}» no es válido.`
    }
    setErrores(locales)
    if (Object.keys(locales).length) return
    const datos = { factor: String(factorNumero), codigo_barras: barras.trim() }
    if (nueva) Object.assign(datos, { producto: producto.id, unidad: Number(unidad) })
    if (puedePrecios) {
      datos.precios = listas.filter((l) => aNumero(precios[l.id]?.precio) !== null).map((l) => ({ lista: l.id, precio: aNumero(precios[l.id].precio) }))
    }
    guardar.mutate(datos, { onError: (e) => setErrores({ general: mensajeDeError(e), ...erroresDeCampo(e) }) })
  }

  return (
    <Modal titulo={nueva ? 'Agregar presentación' : `Editar ${presentacion.unidad_nombre}`} subtitulo={`De «${producto.nombre}». Su unidad base es ${producto.unidad_abreviatura}.`} onCerrar={onCerrar} ancho={620}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={guardar.isPending} className="sin-borde">
          <div className="fila-campos">
            {nueva ? (
              <Campo etiqueta="Unidad" icono="boxes" tipo="select" requerido error={errores.unidad}>
                {(p) => (
                  <select {...p} value={unidad} onChange={(e) => setUnidad(e.target.value)}>
                    <option value="">{unidades.isLoading ? 'Cargando…' : 'Elija la unidad'}</option>
                    {elegibles.map((u) => (
                      <option key={u.id} value={String(u.id)}>{u.nombre} ({u.abreviatura})</option>
                    ))}
                  </select>
                )}
              </Campo>
            ) : (
              <Campo etiqueta="Unidad" icono="boxes">{(p) => <input {...p} value={presentacion.unidad_nombre} readOnly disabled />}</Campo>
            )}
            <Campo etiqueta={`Cuántas ${producto.unidad_abreviatura} trae`} icono="calculator" requerido error={errores.factor} ayuda={factorNumero > 0 && unidadElegida ? `1 ${unidadElegida.nombre} = ${factorNumero} ${producto.unidad_abreviatura}` : 'Por ejemplo, 12 si la caja trae 12 unidades.'}>
              {(p) => <input {...p} inputMode="decimal" placeholder="Ej. 12" value={factor} onChange={(e) => setFactor(e.target.value)} />}
            </Campo>
            <Campo etiqueta="Código de barras (opcional)" icono="scan" error={errores.codigo_barras} ayuda="Si la caja o docena trae el suyo, al escanearlo se reconoce esa presentación.">
              {(p) => <input {...p} inputMode="numeric" maxLength={40} placeholder="Ej. 7750182009999" value={barras} onChange={(e) => setBarras(e.target.value)} />}
            </Campo>
          </div>

          {puedePrecios && listas.length > 0 && (
            <div className="marco-tabla">
              <table className="tabla-datos tabla-precios">
                <thead>
                  <tr>
                    <th>Lista</th>
                    <th>{calc.encabezado}</th>
                    <th>Precio de venta (S/)</th>
                  </tr>
                </thead>
                <tbody>
                  {listas.map((l) => (
                    <tr key={l.id}>
                      <td><strong>{l.nombre}</strong></td>
                      <td>
                        <input aria-label={`${calc.nombre} de ${l.nombre}`} inputMode="decimal" value={precios[l.id]?.pct ?? calc.aPorcentaje(costoPresentacion, precios[l.id]?.precio)} disabled={!costoPresentacion} title={costoPresentacion ? undefined : 'Falta el costo del producto o el factor'} placeholder={costoPresentacion ? '0' : '—'} onChange={(e) => ponerPorcentaje(l.id, e.target.value)} />
                      </td>
                      <td>
                        <input aria-label={`Precio de ${l.nombre}`} inputMode="decimal" value={precios[l.id]?.precio ?? ''} placeholder="0.00" onChange={(e) => ponerPrecio(l.id, e.target.value)} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {puedePrecios && costoPresentacion && <p className="celda-suave">Costo de esta presentación: {soles(costoPresentacion)} ({factorNumero} × el costo de {soles(costoBase)} por {producto.unidad_abreviatura}).</p>}
          {errores.precios && <p role="alert" className="campo-error">{errores.precios}</p>}
        </fieldset>
        {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={guardar.isPending}>Cancelar</button>
          <button type="submit" className="primario" disabled={guardar.isPending}>{guardar.isPending ? 'Guardando…' : nueva ? 'Agregar' : 'Guardar cambios'}</button>
        </div>
      </form>
    </Modal>
  )
}
