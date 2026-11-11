import { memo } from 'react'
import BuscadorAsincrono from '../../../shared/components/BuscadorAsincrono'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import { cantidad as formatoCantidad } from '../../almacen/inventario'
import { lineaDeProducto, presentacionesActivas } from '../compras'

/** Un producto a cotizar. Memorizada: al escribir en una no se vuelven a dibujar las demás. */
const FilaCotizacion = memo(function FilaCotizacion({ linea, indice, errores, disabled, onCambiar, onQuitar }) {
  const { producto } = linea
  const presentaciones = presentacionesActivas(producto)
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
      </td>
      <td className="num">
        <input aria-label={`Cantidad de ${producto.nombre}`} className="compra-numero" inputMode="decimal" value={linea.cantidad} disabled={disabled} aria-invalid={Boolean(errores?.cantidad)} onChange={cambiar('cantidad')} />
        {errores?.cantidad && (
          <small role="alert" className="campo-error">
            {errores.cantidad}
          </small>
        )}
      </td>
      <td className="centrado">
        <button type="button" className="accion-icono peligro-suave" aria-label={`Quitar ${producto.nombre}`} title="Quitar" disabled={disabled} onClick={() => onQuitar(linea.id)}>
          <Icono nombre="papelera" tam={19} />
        </button>
      </td>
    </tr>
  )
})

/** Productos de la cotización: un buscador arriba y la tabla de cantidades debajo (sin precios). */
export default function LineasCotizacion({ lineas, onLineas, errores, disabled }) {
  const agregar = (producto) => {
    const existente = lineas.find((l) => l.producto.id === producto.id && !l.presentacion)
    if (existente) {
      onLineas((previas) => previas.map((l) => (l.id === existente.id ? { ...l, cantidad: String((Number(String(l.cantidad).replace(',', '.')) || 0) + 1) } : l)))
      return
    }
    onLineas((previas) => [...previas, lineaDeProducto(producto)])
  }
  const cambiar = (id, campo, valor) => onLineas((previas) => previas.map((l) => (l.id === id ? { ...l, [campo]: valor } : l)))
  const quitar = (id) => onLineas((previas) => previas.filter((l) => l.id !== id))

  return (
    <>
      <div className="compra-agregar">
        <BuscadorAsincrono
          clave="productos-cotizacion"
          url="/mantenimiento/productos/"
          parametros={{ tipo: 'BIEN', estado: 'ACTIVO' }}
          etiqueta="Agregar producto"
          placeholder="Escribe el nombre o código, o escanea el código de barras…"
          icono="package"
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
              <th className="centrado">
                <span className="sr-only">Quitar</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {lineas.length === 0 && <FilaVacia columnas={5} icono="package" titulo="Aún no agregaste productos" descripcion="Busca arriba por nombre o código. Los precios los darán los proveedores." />}
            {lineas.map((linea, i) => (
              <FilaCotizacion key={linea.id} linea={linea} indice={i} errores={errores[linea.id]} disabled={disabled} onCambiar={cambiar} onQuitar={quitar} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
