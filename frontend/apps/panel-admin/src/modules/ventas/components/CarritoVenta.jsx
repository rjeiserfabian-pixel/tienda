import { useState } from 'react'
import { Icono } from '../../../shared/components/IconosPanel'
import { cantidad as formatoCantidad } from '../../almacen/inventario'
import { aNumero } from '../../almacen/utilidades'
import { dinero } from '../../compras/compras'
import { ESTADOS_PRECIO, cambiarSurtidor, maximoDeLinea } from '../ventas'
import { diaMes, useAntiguedadVenta } from '../hooks/useAntiguedadVenta'
import { useSeriesSugeridas } from '../hooks/useSeriesSugeridas'
import SeriesVentaModal from './SeriesVentaModal'

/** Una línea del carrito: quién la surte (A/B), unidad, cantidad, precio sin IGV editable e importe. */
function Linea({ indice, linea, calculo, empresa, candidatas, afectaciones, moneda, disabled, aviso, sugerirSeries, onCambiar, onQuitar }) {
  const [series, setSeries] = useState(false)
  const [escribiendo, setEscribiendo] = useState(null) // lo que se está tecleando en el precio (puede quedar vacío un momento)
  const maximo = maximoDeLinea(linea)
  const n = aNumero(linea.cantidad)
  const pasa = maximo !== null && n !== null && n > maximo
  const estado = calculo ? ESTADOS_PRECIO[calculo.estado_precio] : null
  const puedeCambiar = linea.ficha.controla_stock && candidatas.length > 1
  const poner = (campos) => onCambiar({ ...linea, ...campos })
  useSeriesSugeridas(linea, onCambiar, sugerirSeries && !disabled) // propone las series más antiguas

  return (
    <tr>
      <td className="centrado celda-suave">{indice + 1}</td>
      <td className="compra-celda-producto">
        <strong title={linea.ficha.nombre}>{linea.ficha.nombre}</strong>
        <span className="sub-texto">
          {[linea.ficha.codigo, maximo !== null ? `hay ${formatoCantidad(maximo)}` : 'servicio'].filter(Boolean).join(' · ')}
        </span>
        {aviso && (
          <span className="pos-aviso-antiguo" role="note">
            <Icono nombre="reloj" tam={14} /> Las unidades más antiguas ingresaron el {diaMes(aviso.ingreso)} ({aviso.dias} días): despache primero esas.
          </span>
        )}
        {linea.ficha.lleva_serie && (
          <button type="button" className={`pos-chip${linea.series.length === n ? ' listo' : ''}`} disabled={disabled} onClick={() => setSeries(true)}>
            <Icono nombre="scan" tam={15} /> {linea.series.length === n ? `Series listas (${linea.series.length})` : `Registrar series (${linea.series.length}/${n ?? 0})`}
          </button>
        )}
        {estado?.texto && (
          <span className="pildora" data-tono={estado.tono}>
            {estado.texto}
            {calculo.minimo ? ` · mín. ${dinero(calculo.minimo, moneda)}` : ''}
          </span>
        )}
      </td>
      <td>
        <button
          type="button"
          className="pos-insignia"
          data-letra={empresa?.letra}
          disabled={disabled || !puedeCambiar}
          title={puedeCambiar ? `Surte ${empresa?.nombre}. Toca para pasarlo a la otra empresa.` : `Surte ${empresa?.nombre}`}
          aria-label={`Surte ${empresa?.nombre}${puedeCambiar ? '. Cambiar de empresa' : ''}`}
          onClick={() => onCambiar(cambiarSurtidor(linea, candidatas))}
        >
          {empresa?.letra}
        </button>
      </td>
      <td>
        <span className="celda-suave">{linea.ficha.unidad || '—'}</span>
      </td>
      <td className="num">
        <input aria-label={`Cantidad de ${linea.ficha.nombre}`} className="compra-numero" inputMode="decimal" value={linea.cantidad} disabled={disabled} aria-invalid={pasa} onChange={(e) => poner({ cantidad: e.target.value.replace(',', '.'), series: [] })} />
        {pasa && <small role="alert" className="campo-error">Solo hay {formatoCantidad(maximo)}.</small>}
      </td>
      <td className="num">
        <input
          aria-label={`Precio unitario de ${linea.ficha.nombre}`}
          className="compra-numero"
          inputMode="decimal"
          title="Es el precio de la lista: puedes escribir otro precio (sin IGV)."
          value={escribiendo ?? (linea.precio !== '' ? linea.precio : calculo ? Number(calculo.precio_lista).toFixed(2) : '')}
          disabled={disabled}
          onChange={(e) => {
            const texto = e.target.value.replace(',', '.')
            setEscribiendo(texto)
            poner({ precio: texto })
          }}
          onBlur={() => setEscribiendo(null)}
        />
      </td>
      <td>
        <select aria-label={`Afectación del IGV de ${linea.ficha.nombre}`} value={linea.afectacion} disabled={disabled} onChange={(e) => poner({ afectacion: e.target.value })}>
          <option value="">{calculo ? `Automática: ${calculo.afectacion}` : 'Automática'}</option>
          {afectaciones.map((a) => (
            <option key={a.codigo} value={a.codigo}>
              {a.nombre}
            </option>
          ))}
        </select>
      </td>
      <td className="num">
        <strong>{calculo ? dinero(calculo.total, moneda) : '—'}</strong>
        {calculo && Number(calculo.igv) > 0 && <span className="sub-texto">con IGV</span>}
      </td>
      <td className="centrado">
        <button type="button" className="accion-icono peligro-suave" aria-label={`Quitar ${linea.ficha.nombre}`} title="Quitar" disabled={disabled} onClick={onQuitar}>
          <Icono nombre="papelera" tam={19} />
        </button>
        {series && <SeriesVentaModal linea={linea} onGuardar={(lista) => poner({ series: lista })} onCerrar={() => setSeries(false)} />}
      </td>
    </tr>
  )
}

/** El carrito, en una tabla como la de las compras: producto, empresa que surte, unidad, cantidad, precio e importe. */
export default function CarritoVenta({ lineas, calculos, empresas, candidatas, afectaciones = [], moneda, disabled, sugerirSeries = false, onCambiar, onQuitar }) {
  const avisos = useAntiguedadVenta(lineas)
  if (lineas.length === 0) {
    return (
      <div className="pos-carrito-vacio">
        <Icono nombre="cart" tam={38} />
        <p>El carrito está vacío.</p>
        <span className="celda-suave">Escanea un producto o toca «Agregar» en el catálogo.</span>
      </div>
    )
  }
  return (
    <div className="marco-tabla compra-tabla">
      <table className="tabla-datos" aria-label="Productos del carrito">
        <thead>
          <tr>
            <th className="centrado">#</th>
            <th>Producto</th>
            <th>Empresa</th>
            <th>Unidad</th>
            <th className="num">Cantidad</th>
            <th className="num">Precio unitario</th>
            <th>IGV</th>
            <th className="num">Importe</th>
            <th className="centrado">
              <span className="sr-only">Quitar</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {lineas.map((l, i) => (
            <Linea key={l.id} indice={i} linea={l} calculo={calculos.get(l.id)} empresa={empresas.find((e) => e.id === l.empresa)} candidatas={candidatas} afectaciones={afectaciones} moneda={moneda} disabled={disabled} sugerirSeries={sugerirSeries} aviso={avisos[`${l.empresa}:${l.almacen}:${l.ficha.id}`]} onCambiar={onCambiar} onQuitar={() => onQuitar(l.id)} />
          ))}
        </tbody>
      </table>
    </div>
  )
}
