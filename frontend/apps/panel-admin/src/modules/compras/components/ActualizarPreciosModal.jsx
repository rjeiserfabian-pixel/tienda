import { useQueries } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, mensajeDeError } from '../../../core/api/client'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import { useCalculoPrecios } from '../../../shared/hooks/useCalculoPrecios'
import { aNumero, soles } from '../../almacen/utilidades'
import { inicialPrecios, numeroInterno } from '../compras'
import '../../almacen/inventario.css'

/** Productos de la compra con su costo por unidad base (valor + IGV si va al costo + flete). */
function productosDe(compra) {
  const mapa = new Map()
  for (const l of compra.lineas) {
    const p = mapa.get(l.producto) ?? { id: l.producto, nombre: l.producto_nombre, codigo: l.producto_codigo, costo: 0, base: 0 }
    p.costo += Number(l.costo_soles)
    p.base += Number(l.cantidad_base)
    mapa.set(l.producto, p)
  }
  return [...mapa.values()].map((p) => ({ ...p, costoUnitario: p.base > 0 ? p.costo / p.base : 0 }))
}

/** Costo y precios por lista de un producto. Con `costoFijo` el costo solo se muestra (es una referencia). */
export function BloqueProducto({ producto, detalle, listas, estado, disabled, costoFijo = false, onCambio }) {
  const calc = useCalculoPrecios()
  const { costo, precios } = estado
  const costoAnterior = aNumero(detalle.costo) ?? 0
  // Cada fila guarda el precio; el porcentaje solo mientras se escribe (si no, se deriva del precio y el costo).
  const cambiarCosto = (valor) => onCambio({ costo: valor, precios: Object.fromEntries(Object.entries(precios).map(([id, p]) => [id, { precio: p.precio }])) })
  const cambiarPrecio = (id, precio) => onCambio({ costo, precios: { ...precios, [id]: { precio } } })
  const cambiarPorcentaje = (id, pct) => onCambio({ costo, precios: { ...precios, [id]: { pct, precio: calc.aPrecio(costo, pct) } } })
  const hayCosto = (aNumero(costo) ?? 0) > 0

  return (
    <section className="precios-bloque" aria-label={producto.nombre}>
      <header>
        <div>
          <strong>{producto.nombre}</strong>
          <span className="sub-texto">{producto.codigo}</span>
        </div>
        <label className="precios-costo">
          <span>
            Costo nuevo (S/) <small className="celda-suave">antes {soles(costoAnterior)}</small>
          </span>
          <input inputMode="decimal" aria-label={`Costo nuevo de ${producto.nombre}`} value={costo} disabled={disabled || costoFijo} onChange={(e) => cambiarCosto(e.target.value)} />
        </label>
      </header>
      {listas.length > 0 && (
        <table className="tabla-datos tabla-precios">
          <thead>
            <tr>
              <th>Lista</th>
              <th>{calc.encabezado}</th>
              <th>Precio de venta (S/)</th>
            </tr>
          </thead>
          <tbody>
            {listas.map((lista) => {
              const fila = precios[lista.id] ?? { precio: '' }
              const bajoCosto = hayCosto && aNumero(fila.precio) !== null && aNumero(fila.precio) < aNumero(costo)
              return (
                <tr key={lista.id}>
                  <td>
                    <strong>{lista.nombre}</strong>
                    {lista.es_principal && <small className="celda-suave"> · principal</small>}
                  </td>
                  <td>
                    <input aria-label={`${calc.nombre} de ${lista.nombre} para ${producto.nombre}`} inputMode="decimal" value={fila.pct ?? calc.aPorcentaje(costo, fila.precio)} disabled={disabled || !hayCosto} placeholder={hayCosto ? '0' : '—'} onChange={(e) => cambiarPorcentaje(lista.id, e.target.value)} />
                  </td>
                  <td>
                    <input aria-label={`Precio de ${lista.nombre} para ${producto.nombre}`} aria-invalid={bajoCosto} inputMode="decimal" value={fila.precio} disabled={disabled} placeholder="0.00" onChange={(e) => cambiarPrecio(lista.id, e.target.value)} />
                    {bajoCosto && <small className="campo-error"> Por debajo del costo</small>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </section>
  )
}

function Editor({ productos, detalles, listas, compra, propuestos, onCerrar }) {
  const [estados, setEstados] = useState(() => Object.fromEntries(productos.map((p, i) => [p.id, inicialPrecios(p.costoUnitario, detalles[i], propuestos?.[p.id])])))
  const [error, setError] = useState('')

  /** Solo se envía lo que cambió respecto de lo guardado en el producto. */
  const cambiados = productos.flatMap((p, i) => {
    const detalle = detalles[i]
    const estado = estados[p.id]
    const costo = aNumero(estado.costo)
    const originales = Object.fromEntries((detalle.precios ?? []).map((x) => [x.lista, x.precio === null ? null : Number(x.precio)]))
    const precios = listas.filter((l) => aNumero(estado.precios[l.id]?.precio) !== null).map((l) => ({ lista: l.id, precio: aNumero(estado.precios[l.id].precio) }))
    const cambioCosto = costo !== null && Math.abs(costo - (aNumero(detalle.costo) ?? 0)) > 0.00005
    const cambioPrecio = precios.some((x) => originales[x.lista] !== x.precio)
    return cambioCosto || cambioPrecio ? [{ producto: p, costo, precios }] : []
  })

  const guardar = useMutacion({
    mutationFn: async () => {
      const fallidos = []
      for (const { producto, costo, precios } of cambiados) {
        try {
          await api.patch(`/mantenimiento/productos/${producto.id}/`, { ...(costo !== null ? { costo } : {}), precios })
        } catch (e) {
          fallidos.push(`${producto.nombre} (${mensajeDeError(e)})`)
        }
      }
      if (fallidos.length) throw new Error(`No se pudo actualizar: ${fallidos.join('; ')}`)
      return cambiados.length
    },
    invalidar: [['productos'], ['opciones']],
    exito: (n) => `${n} ${n === 1 ? 'producto actualizado' : 'productos actualizados'}.`,
    alExito: onCerrar,
    avisarError: false,
  })

  return (
    <>
      <p className="celda-suave">
        Compra N° {numeroInterno(compra)} registrada. El costo nuevo es lo que costó cada unidad en esta compra (con IGV si va al costo y con el flete). Si lo aceptas, reemplaza el costo del producto; el precio de venta no cambia salvo que lo edites o lo hayas dejado preparado en la compra.
      </p>
      {listas.length === 0 && (
        <p className="compra-aviso">
          Aún no hay listas de precios. <Link to="/mantenimiento/listas-precio">Créalas aquí</Link> para poner precios de venta.
        </p>
      )}
      <div className="precios-lista">
        {productos.map((p, i) => (
          <BloqueProducto key={p.id} producto={p} detalle={detalles[i]} listas={listas} estado={estados[p.id]} disabled={guardar.isPending} onCambio={(nuevo) => setEstados((previos) => ({ ...previos, [p.id]: nuevo }))} />
        ))}
      </div>
      {error && (
        <p role="alert" className="campo-error">
          {error}
        </p>
      )}
      <div className="modal-pie">
        <button type="button" onClick={onCerrar} disabled={guardar.isPending}>
          Omitir por ahora
        </button>
        <button
          type="button"
          className="primario"
          disabled={guardar.isPending || cambiados.length === 0}
          onClick={() => {
            setError('')
            guardar.mutate(undefined, { onError: (e) => setError(e.message) })
          }}
        >
          {guardar.isPending ? 'Guardando…' : cambiados.length ? `Guardar cambios (${cambiados.length})` : 'Guardar cambios'}
        </button>
      </div>
    </>
  )
}

/**
 * Después de registrar una compra: el costo cambió, ¿cambian los precios de venta? Muestra el costo
 * nuevo por producto y los precios por lista, con utilidad y precio ligados (se escribe uno y se
 * calcula el otro). Solo guarda lo que se modificó. Lo ven quienes pueden cambiar precios.
 */
export default function ActualizarPreciosModal({ compra, propuestos, onCerrar }) {
  const productos = useMemo(() => productosDe(compra), [compra])
  const listas = useOpciones('/mantenimiento/listas-precio/')
  const consultas = useQueries({
    queries: productos.map((p) => ({
      queryKey: ['productos', 'detalle', p.id],
      queryFn: ({ signal }) => api.get(`/mantenimiento/productos/${p.id}/`, { signal }).then((r) => r.data),
      staleTime: 0,
    })),
  })
  const cargando = consultas.some((c) => c.isLoading) || listas.isLoading
  const fallo = consultas.find((c) => c.isError) ?? (listas.isError ? listas : null)
  const detalles = consultas.map((c) => c.data)

  return (
    <Modal titulo="Actualizar precios de venta" subtitulo="¿El costo cambió? Ajusta lo que cobras." onCerrar={onCerrar} ancho={900}>
      <EstadoConsulta consulta={{ isLoading: cargando, isError: Boolean(fallo), error: fallo?.error, refetch: () => consultas.forEach((c) => c.refetch()) }} hayDatos={detalles.every(Boolean)}>
        {detalles.every(Boolean) && <Editor productos={productos} detalles={detalles} listas={listas.data ?? []} compra={compra} propuestos={propuestos} onCerrar={onCerrar} />}
      </EstadoConsulta>
      {(cargando || fallo) && (
        <div className="modal-pie">
          <button type="button" onClick={onCerrar}>
            Omitir por ahora
          </button>
        </div>
      )}
    </Modal>
  )
}
