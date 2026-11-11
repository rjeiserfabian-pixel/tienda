import { useEffect, useRef, useState } from 'react'
import BuscadorAsincrono from '../../../shared/components/BuscadorAsincrono'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import SeriesModal from '../../almacen/components/SeriesModal'
import { aNumero } from '../../almacen/utilidades'
import { lineaDeProducto } from '../compras'
import FilaLineaCompra from './FilaLineaCompra'
import PreciosLineaModal from './PreciosLineaModal'

/**
 * Productos de la compra. Arriba, un buscador siempre listo: se escribe o se escanea el código y
 * Enter agrega el producto (si ya estaba sin series, suma una unidad). Debajo, la tabla editable.
 * `resultados` son los cálculos del servidor por id de línea.
 */
export default function LineasCompra({ lineas, onLineas, resultados, moneda, afectaciones, ubicaciones, errores, disabled, puedePrecios, listas }) {
  const [escribiendo, setEscribiendo] = useState(null) // id de la línea cuyas series se escriben
  const enfocar = useRef(null) // id de la línea recién agregada: el cursor va a su cantidad
  const [conPrecios, setConPrecios] = useState(null) // id de la línea cuyos precios de venta se preparan
  const buscador = useRef(null)
  const lineaDeSeries = lineas.find((l) => l.id === escribiendo)
  const sinConfirmar = lineas.filter((l) => l.precioSugerido).length
  const lineaDePrecios = lineas.find((l) => l.id === conPrecios)
  const calculoDePrecios = lineaDePrecios && resultados[lineaDePrecios.id]
  // Costo provisional por unidad base, según el cálculo del servidor.
  const costoUnitario = calculoDePrecios && aNumero(calculoDePrecios.cantidad_base) ? Number(calculoDePrecios.costo_soles) / Number(calculoDePrecios.cantidad_base) : null

  useEffect(() => {
    if (enfocar.current === null) return
    document.querySelector(`tr[data-linea="${enfocar.current}"] input`)?.select()
    enfocar.current = null
  }, [lineas])

  const agregar = (producto) => {
    const existente = lineas.find((l) => l.producto.id === producto.id && !producto.lleva_serie && !l.presentacion)
    if (existente) {
      onLineas((previas) => previas.map((l) => (l.id === existente.id ? { ...l, cantidad: String((Number(String(l.cantidad).replace(',', '.')) || 0) + 1) } : l)))
      enfocar.current = existente.id
      return
    }
    const nueva = lineaDeProducto(producto)
    // Se propone el costo que el catálogo ya tiene (solo lo ve quien puede ver costos); se puede editar.
    if (aNumero(producto.costo) > 0) {
      nueva.precio = String(Number(producto.costo))
      nueva.precioSugerido = true
    }
    onLineas((previas) => [...previas, nueva])
    enfocar.current = nueva.id
    if (producto.lleva_serie) setEscribiendo(nueva.id)
  }

  const cambiar = (id, campo, valor) =>
    onLineas((previas) =>
      previas.map((l) => {
        if (l.id !== id) return l
        const nueva = { ...l, [campo]: valor }
        if (campo === 'precio') nueva.precioSugerido = false // lo escribió la persona
        if (campo === 'presentacion' && l.precioSugerido) {
          // El costo del catálogo es por unidad base: una caja cuesta su factor por ese costo.
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
          clave="productos-compra"
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
                {p.lleva_serie ? ' · lleva serie' : ''}
              </span>
            </>
          )}
        />
      </div>
      {sinConfirmar > 1 && (
        <p className="compra-aviso compra-confirmar-todos">
          {sinConfirmar} precios vienen del catálogo. Compáralos con tu factura y corrige los que cambiaron.{' '}
          <button type="button" disabled={disabled} onClick={() => onLineas((previas) => previas.map((l) => ({ ...l, precioSugerido: false })))}>
            Confirmar todos
          </button>
        </p>
      )}
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
              {puedePrecios && <th className="centrado">Venta</th>}
              <th className="centrado">
                <span className="sr-only">Quitar</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {lineas.length === 0 && <FilaVacia columnas={puedePrecios ? 9 : 8} icono="package" titulo="Aún no agregaste productos" descripcion="Busca arriba por nombre o código, o escanea el código de barras." />}
            {lineas.map((linea, i) => (
              <FilaLineaCompra
                key={linea.id}
                linea={linea}
                indice={i}
                calculo={resultados[linea.id]}
                moneda={moneda}
                afectaciones={afectaciones}
                ubicaciones={ubicaciones}
                errores={errores[linea.id]}
                disabled={disabled}
                puedePrecios={puedePrecios}
                onCambiar={cambiar}
                onQuitar={quitar}
                onSeries={setEscribiendo}
                onPrecios={setConPrecios}
              />
            ))}
          </tbody>
        </table>
      </div>
      {lineaDeSeries && (
        <SeriesModal
          producto={lineaDeSeries.producto}
          series={lineaDeSeries.series}
          conDatos
          onGuardar={(lista) => {
            cambiar(lineaDeSeries.id, 'series', lista)
            setEscribiendo(null)
          }}
          onCerrar={() => setEscribiendo(null)}
        />
      )}
      {lineaDePrecios && (
        <PreciosLineaModal
          linea={lineaDePrecios}
          costoUnitario={costoUnitario}
          listas={listas}
          onGuardar={(precios) => {
            cambiar(lineaDePrecios.id, 'ventaPrecios', precios)
            setConPrecios(null)
          }}
          onCerrar={() => setConPrecios(null)}
        />
      )}
    </>
  )
}
