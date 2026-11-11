import { memo, useEffect, useRef } from 'react'
import BuscadorAsincrono from '../../../shared/components/BuscadorAsincrono'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import { cantidad as formatoCantidad } from '../../almacen/inventario'
import { aNumero } from '../../almacen/utilidades'
import { dinero, lineaDeProducto, presentacionesActivas } from '../compras'

/** Una línea de la orden. Está memorizada: al escribir en una no se vuelven a dibujar las demás. */
const FilaOrden = memo(function FilaOrden({ linea, indice, calculo, moneda, afectaciones, errores, disabled, onCambiar, onQuitar }) {
  const { producto } = linea
  const presentaciones = presentacionesActivas(producto)
  const presentacion = presentaciones.find((p) => String(p.id) === String(linea.presentacion))
  const cantidad = aNumero(linea.cantidad) ?? 0
  const enBase = presentacion ? cantidad * Number(presentacion.factor) : null
  const importe = calculo ? calculo.total : String(cantidad * (aNumero(linea.precio) ?? 0))
  const cambiar = (campo) => (e) => onCambiar(linea.id, campo, e.target.value)

  return (
    <tr data-linea={linea.id}>
      <td className="centrado celda-suave">{indice + 1}</td>
      <td className="compra-celda-producto">
        <strong>{producto.nombre}</strong>
        <span className="sub-texto">{producto.codigo}</span>
      </td>
      <td>
        {presentaciones.length > 0 ? (
          <select aria-label={`Unidad de ${producto.nombre}`} value={linea.presentacion} disabled={disabled} onChange={cambiar('presentacion')}>
            <option value="">{producto.unidad_abreviatura}</option>
            {presentaciones.map((p) => (
              <option key={p.id} value={p.id}>
                {p.unidad_abreviatura} (x{formatoCantidad(p.factor)})
              </option>
            ))}
          </select>
        ) : (
          <span className="celda-suave">{producto.unidad_abreviatura}</span>
        )}
        {enBase !== null && enBase > 0 && (
          <span className="sub-texto">
            = {formatoCantidad(enBase)} {producto.unidad_abreviatura}
          </span>
        )}
      </td>
      <td className="num">
        <input aria-label={`Cantidad de ${producto.nombre}`} className="compra-numero" inputMode="decimal" value={linea.cantidad} disabled={disabled} aria-invalid={Boolean(errores?.cantidad)} onChange={cambiar('cantidad')} />
        {errores?.cantidad && (
          <small role="alert" className="campo-error">
            {errores.cantidad}
          </small>
        )}
      </td>
      <td className="num">
        <input aria-label={`Precio de ${producto.nombre}`} className={`compra-numero${linea.precioSugerido ? ' sugerido' : ''}`} inputMode="decimal" placeholder="0.00" value={linea.precio} disabled={disabled} aria-invalid={Boolean(errores?.precio)} title={linea.precioSugerido ? 'Costo del catálogo: corrígelo con el precio que pactaste' : undefined} onChange={cambiar('precio')} />
        {errores?.precio && (
          <small role="alert" className="campo-error">
            {errores.precio}
          </small>
        )}
      </td>
      <td>
        <select aria-label={`Afectación del IGV de ${producto.nombre}`} value={linea.afectacion} disabled={disabled} onChange={cambiar('afectacion')}>
          <option value="">{calculo ? `Automática: ${calculo.afectacion_nombre}` : 'Automática'}</option>
          {afectaciones.map((a) => (
            <option key={a.codigo} value={a.codigo}>
              {a.nombre}
            </option>
          ))}
        </select>
      </td>
      <td className="num">
        <strong>{dinero(importe, moneda)}</strong>
      </td>
      <td className="centrado">
        <button type="button" className="accion-icono peligro-suave" aria-label={`Quitar ${producto.nombre}`} title="Quitar" disabled={disabled} onClick={() => onQuitar(linea.id)}>
          <Icono nombre="papelera" tam={19} />
        </button>
      </td>
    </tr>
  )
})

/**
 * Productos de la orden. Arriba, un buscador siempre listo (nombre, código o código de barras);
 * debajo, la tabla editable. `resultados` son los cálculos del servidor por id de línea.
 */
export default function LineasOrden({ lineas, onLineas, resultados, moneda, afectaciones, errores, disabled }) {
  const enfocar = useRef(null) // id de la línea recién agregada: el cursor va a su cantidad
  const buscador = useRef(null)

  useEffect(() => {
    if (enfocar.current === null) return
    document.querySelector(`tr[data-linea="${enfocar.current}"] input`)?.select()
    enfocar.current = null
  }, [lineas])

  const agregar = (producto) => {
    const existente = lineas.find((l) => l.producto.id === producto.id && !l.presentacion)
    if (existente) {
      onLineas((previas) => previas.map((l) => (l.id === existente.id ? { ...l, cantidad: String((Number(String(l.cantidad).replace(',', '.')) || 0) + 1) } : l)))
      enfocar.current = existente.id
      return
    }
    const nueva = lineaDeProducto(producto)
    // Se propone el costo que el catálogo ya tiene (solo lo ve quien puede ver costos); se puede corregir.
    if (aNumero(producto.costo) > 0) {
      nueva.precio = String(Number(producto.costo))
      nueva.precioSugerido = true
    }
    onLineas((previas) => [...previas, nueva])
    enfocar.current = nueva.id
  }

  const cambiar = (id, campo, valor) =>
    onLineas((previas) =>
      previas.map((l) => {
        if (l.id !== id) return l
        const nueva = { ...l, [campo]: valor }
        if (campo === 'precio') nueva.precioSugerido = false // lo escribió la persona
        if (campo === 'presentacion' && l.precioSugerido) {
          const factor = valor ? Number(l.producto.presentaciones?.find((x) => String(x.id) === String(valor))?.factor ?? 1) : 1
          nueva.precio = String(Number((Number(l.producto.costo) * factor).toFixed(4)))
        }
        return nueva
      }),
    )
  const quitar = (id) => onLineas((previas) => previas.filter((l) => l.id !== id))

  return (
    <>
      <div className="compra-agregar">
        <BuscadorAsincrono
          clave="productos-orden"
          url="/mantenimiento/productos/"
          parametros={{ tipo: 'BIEN', estado: 'ACTIVO' }}
          etiqueta="Agregar producto"
          placeholder="Escribe el nombre o código, o escanea el código de barras…"
          icono="package"
          inputRef={buscador}
          disabled={disabled}
          onElegir={agregar}
          mostrar={(p) => (
            <>
              <strong>{p.nombre}</strong>
              <span className="sub-texto">
                {p.codigo} · {p.unidad_abreviatura}
              </span>
            </>
          )}
        />
      </div>
      <div className="marco-tabla compra-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th className="centrado">#</th>
              <th>Producto</th>
              <th>Unidad</th>
              <th className="num">Cantidad</th>
              <th className="num">Precio unit.</th>
              <th>IGV</th>
              <th className="num">Importe</th>
              <th className="centrado">
                <span className="sr-only">Quitar</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {lineas.length === 0 && <FilaVacia columnas={8} icono="package" titulo="Aún no agregaste productos" descripcion="Busca arriba por nombre o código, o escanea el código de barras." />}
            {lineas.map((linea, i) => (
              <FilaOrden key={linea.id} linea={linea} indice={i} calculo={resultados[linea.id]} moneda={moneda} afectaciones={afectaciones} errores={errores[linea.id]} disabled={disabled} onCambiar={cambiar} onQuitar={quitar} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
