import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import { useState } from 'react'
import { nuevaLinea } from '../inventario'
import SelectorProducto from './SelectorProducto'
import SeriesModal from './SeriesModal'

const importeLinea = (cantidad, precio) => {
  const total = Number(String(cantidad).replace(',', '.')) * Number(String(precio).replace(',', '.'))
  return Number.isFinite(total) && total > 0 ? total.toLocaleString('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'
}

/**
 * Productos del movimiento: cada fila lleva producto, cantidad y (en las entradas) el precio de
 * compra sin convertir, tal como figura en el comprobante. Si el producto lleva serie o IMEI, la
 * cantidad sale sola de las series escritas (una por línea). `errores` se indexa por id de línea.
 */
export default function LineasMovimiento({ lineas, onCambiar, tipo, conPrecio = tipo === 'ENTRADA', ubicaciones = [], errores = {}, disabled = false }) {
  const cambiar = (id, campo, valor) => onCambiar(lineas.map((l) => (l.id === id ? { ...l, [campo]: valor } : l)))
  const quitar = (id) => onCambiar(lineas.filter((l) => l.id !== id))
  const [escribiendo, setEscribiendo] = useState(null) // id de la línea cuyas series se escriben
  const lineaDeSeries = lineas.find((l) => l.id === escribiendo)

  return (
    <div className="lineas-editor">
      {lineas.map((linea, i) => {
        const e = errores[linea.id] ?? {}
        const conSerie = Boolean(linea.producto?.lleva_serie)
        const series = conSerie ? linea.series : []
        return (
          <div className="linea-bloque" key={linea.id}>
            <div className="linea-cabecera">
              <span className="linea-numero" aria-hidden="true">
                {i + 1}
              </span>
              <SelectorProducto valor={linea.producto} onElegir={(p) => cambiar(linea.id, 'producto', p)} etiqueta={`Producto ${i + 1}`} error={e.producto} disabled={disabled} />
              <button type="button" className="accion-icono peligro-suave" aria-label={`Quitar el producto ${i + 1}`} title="Quitar" disabled={disabled || lineas.length === 1} onClick={() => quitar(linea.id)}>
                <Icono nombre="papelera" tam={19} />
              </button>
            </div>
            <div className={conPrecio ? 'linea-valores con-precio' : 'linea-valores'}>
              <Campo etiqueta="Cantidad" error={e.cantidad} ayuda={conSerie ? 'Según las series' : undefined}>
                {(p) =>
                  conSerie ? (
                    <input {...p} value={series.length} readOnly />
                  ) : (
                    <input {...p} inputMode="decimal" placeholder="0" value={linea.cantidad} disabled={disabled} onChange={(ev) => cambiar(linea.id, 'cantidad', ev.target.value)} />
                  )
                }
              </Campo>
              {conPrecio && (
                <Campo etiqueta="Precio unitario" error={e.precio}>
                  {(p) => (
                    <input {...p} inputMode="decimal" placeholder="0.00" value={linea.precio} disabled={disabled} onChange={(ev) => cambiar(linea.id, 'precio', ev.target.value)} />
                  )}
                </Campo>
              )}
              {conPrecio && (
                <div className="linea-importe">
                  <span>Importe</span>
                  <strong>{importeLinea(conSerie ? series.length : linea.cantidad, linea.precio)}</strong>
                </div>
              )}
            </div>
            {ubicaciones.length > 0 && (
              <div className="linea-ubicacion">
                <Campo etiqueta="Ubicación en el almacén (opcional)" icono="ubicacion" tipo="select" error={e.ubicacion}>
                  {(p) => (
                    <select {...p} value={ubicaciones.some((u) => String(u.id) === String(linea.ubicacion)) ? String(linea.ubicacion) : ''} disabled={disabled} onChange={(ev) => cambiar(linea.id, 'ubicacion', ev.target.value)}>
                      <option value="">No cambiar la ubicación</option>
                      {ubicaciones.map((u) => (
                        <option key={u.id} value={String(u.id)}>{u.codigo} · {u.nombre}</option>
                      ))}
                    </select>
                  )}
                </Campo>
              </div>
            )}
            {conSerie && (
              <div className="linea-series">
                <div>
                  <strong>{series.length} {series.length === 1 ? 'serie' : 'series'}</strong>
                  <span className="celda-suave"> de {linea.producto?.nombre}</span>
                  {series.length > 0 && (
                    <span className="linea-series-fichas">
                      {series.slice(0, 3).map((s) => (
                        <span className="pildora" data-tono="gris" key={s.numero}>{s.numero}</span>
                      ))}
                      {series.length > 3 && <span className="celda-suave">y {series.length - 3} más</span>}
                    </span>
                  )}
                </div>
                <button type="button" className="boton-cabecera" disabled={disabled} onClick={() => setEscribiendo(linea.id)}>
                  <Icono nombre="scan" tam={19} /> {series.length ? 'Ver o cambiar series' : 'Escribir series o IMEI'}
                </button>
                {e.series && <p role="alert" className="campo-error">{e.series}</p>}
              </div>
            )}
          </div>
        )
      })}
      {lineaDeSeries && (
        <SeriesModal
          producto={lineaDeSeries.producto}
          series={lineaDeSeries.series}
          conDatos={tipo === 'ENTRADA'}
          onGuardar={(lista) => {
            cambiar(lineaDeSeries.id, 'series', lista)
            setEscribiendo(null)
          }}
          onCerrar={() => setEscribiendo(null)}
        />
      )}
      <div>
        <button type="button" className="boton-cabecera" disabled={disabled || lineas.length >= 200} onClick={() => onCambiar([...lineas, nuevaLinea()])}>
          <Icono nombre="agregar" tam={19} /> Agregar producto
        </button>
      </div>
    </div>
  )
}
