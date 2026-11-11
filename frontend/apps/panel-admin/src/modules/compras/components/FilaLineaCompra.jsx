import { memo } from 'react'
import { Icono } from '../../../shared/components/IconosPanel'
import { cantidad as formatoCantidad } from '../../almacen/inventario'
import { aNumero } from '../../almacen/utilidades'
import { dinero, presentacionesActivas } from '../compras'

/** Costo en soles de cada unidad base que entra al inventario (valor + IGV si va al costo + flete). */
const costoUnitario = (calculo) => {
  const base = aNumero(calculo?.cantidad_base)
  const costo = aNumero(calculo?.costo_soles)
  if (!base || costo === null) return null
  return `S/ ${(costo / base).toLocaleString('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`
}

/**
 * Una línea de la compra. Está memorizada: al escribir en una línea no se vuelven a dibujar las demás.
 * `calculo` es el resultado del servidor para esta línea (afectación propuesta, importe y costo).
 */
function FilaLineaCompra({ linea, indice, calculo, moneda, afectaciones, ubicaciones, errores, disabled, puedePrecios, onCambiar, onQuitar, onSeries, onPrecios }) {
  const { producto } = linea
  const conSerie = Boolean(producto.lleva_serie)
  const presentaciones = conSerie ? [] : presentacionesActivas(producto)
  const presentacion = presentaciones.find((p) => String(p.id) === String(linea.presentacion))
  const cantidad = conSerie ? linea.series.length : (aNumero(linea.cantidad) ?? 0)
  const enBase = presentacion ? cantidad * Number(presentacion.factor) : null
  const importe = calculo ? calculo.total : String(cantidad * (aNumero(linea.precio) ?? 0))
  const costo = costoUnitario(calculo)
  const cambiar = (campo) => (e) => onCambiar(linea.id, campo, e.target.value)

  return (
    <tr data-linea={linea.id}>
      <td className="centrado celda-suave">{indice + 1}</td>
      <td className="compra-celda-producto">
        <strong>{producto.nombre}</strong>
        <span className="sub-texto">{producto.codigo}</span>
        {conSerie && (
          <button type="button" className="compra-boton-series" disabled={disabled} onClick={() => onSeries(linea.id)}>
            <Icono nombre="scan" tam={16} /> {linea.series.length ? `${linea.series.length} serie(s)` : 'Escribir series o IMEI'}
          </button>
        )}
        <input aria-label={`Lote de ${producto.nombre}`} className="compra-lote" maxLength={40} placeholder="Lote (opcional)" value={linea.lote} disabled={disabled} onChange={cambiar('lote')} />
        {ubicaciones.length > 0 && (
          <select aria-label={`Ubicación de ${producto.nombre}`} className="compra-ubicacion" value={ubicaciones.some((u) => String(u.id) === String(linea.ubicacion)) ? String(linea.ubicacion) : ''} disabled={disabled} onChange={cambiar('ubicacion')}>
            <option value="">Ubicación: no cambiar</option>
            {ubicaciones.map((u) => (
              <option key={u.id} value={u.id}>
                {u.codigo} · {u.nombre}
              </option>
            ))}
          </select>
        )}
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
        {enBase !== null && enBase > 0 && <span className="sub-texto">= {formatoCantidad(enBase)} {producto.unidad_abreviatura}</span>}
      </td>
      <td className="num">
        {conSerie ? (
          <strong>{linea.series.length}</strong>
        ) : (
          <input aria-label={`Cantidad de ${producto.nombre}`} className="compra-numero" inputMode="decimal" value={linea.cantidad} disabled={disabled} aria-invalid={Boolean(errores?.cantidad)} onChange={cambiar('cantidad')} />
        )}
        {errores?.cantidad && <small role="alert" className="campo-error">{errores.cantidad}</small>}
      </td>
      <td className="num">
        <input aria-label={`Precio de ${producto.nombre}`} className={`compra-numero${linea.precioSugerido ? ' sugerido' : ''}`} inputMode="decimal" placeholder="0.00" value={linea.precio} disabled={disabled} aria-invalid={Boolean(errores?.precio)} title={linea.precioSugerido ? 'Costo del catálogo: confirma o corrige con el precio de tu factura' : undefined} onChange={cambiar('precio')} />
        {linea.precioSugerido && (
          <button type="button" className="compra-confirmar" disabled={disabled} title="El precio coincide con mi factura" onClick={() => onCambiar(linea.id, 'precioSugerido', false)}>
            ✓ Confirmar precio
          </button>
        )}
        {errores?.precio && <small role="alert" className="campo-error">{errores.precio}</small>}
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
        {costo && <span className="sub-texto">Costo c/u {costo}</span>}
      </td>
      {puedePrecios && (
        <td className="centrado">
          <button
            type="button"
            className={`compra-pv${linea.ventaPrecios ? ' listo' : ''}`}
            disabled={disabled}
            title={linea.ventaPrecios ? 'Precios de venta preparados: se aplican al registrar la compra' : 'Preparar los precios de venta de este producto'}
            aria-label={`Precios de venta de ${producto.nombre}${linea.ventaPrecios ? ' (preparados)' : ''}`}
            onClick={() => onPrecios(linea.id)}
          >
            PV{linea.ventaPrecios ? ' ✓' : ''}
          </button>
        </td>
      )}
      <td className="centrado">
        <button type="button" className="accion-icono peligro-suave" aria-label={`Quitar ${producto.nombre}`} title="Quitar" disabled={disabled} onClick={() => onQuitar(linea.id)}>
          <Icono nombre="papelera" tam={19} />
        </button>
      </td>
    </tr>
  )
}

export default memo(FilaLineaCompra)
