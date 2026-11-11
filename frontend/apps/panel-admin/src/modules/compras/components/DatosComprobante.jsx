import Campo from '../../../shared/components/Campo'
import { hoyIso } from '../../almacen/inventario'

/**
 * Datos del comprobante del proveedor: tipo, serie y número, fechas, almacén de destino, moneda y
 * cómo vienen escritos los precios. `catalogos` trae las listas ya cargadas; `e` los errores por campo.
 */
export default function DatosComprobante({ b, poner, catalogos, resuelto, e, disabled }) {
  const { almacenes, comprobantes } = catalogos
  const tipo = resuelto.tipoCatalogo

  return (
    <>
      <div className="fila-campos">
        <Campo etiqueta="Comprobante" tipo="select" requerido error={e.tipo} ayuda={comprobantes.isError ? 'No se pudieron cargar los tipos de comprobante.' : undefined}>
          {(p) => (
            <select {...p} value={resuelto.tipo} disabled={disabled} onChange={(ev) => poner('tipo', ev.target.value)}>
              {comprobantes.isLoading && <option value="">Cargando…</option>}
              {(comprobantes.data ?? []).map((t) => (
                <option key={t.codigo} value={t.codigo}>
                  {t.nombre}
                </option>
              ))}
            </select>
          )}
        </Campo>
        <Campo etiqueta="Serie" error={e.serie}>
          {(p) => <input {...p} placeholder={tipo?.ejemplo_serie || 'F001'} maxLength={10} value={b.serie} disabled={disabled} onChange={(ev) => poner('serie', ev.target.value.toUpperCase())} />}
        </Campo>
        <Campo etiqueta="Número" requerido error={e.numero}>
          {(p) => <input {...p} placeholder="00001245" maxLength={20} value={b.numero} disabled={disabled} onChange={(ev) => poner('numero', ev.target.value.toUpperCase())} />}
        </Campo>
        <Campo etiqueta="Fecha de emisión" icono="calendario" requerido error={e.fecha}>
          {(p) => <input {...p} type="date" max={hoyIso()} value={b.fecha} disabled={disabled} onChange={(ev) => poner('fecha', ev.target.value)} />}
        </Campo>
      </div>
      <div className="fila-campos">
        <Campo etiqueta="Almacén de destino" tipo="select" requerido error={e.almacen}>
          {(p) => (
            <select {...p} value={resuelto.almacen} disabled={disabled} onChange={(ev) => poner('almacen', ev.target.value)}>
              {almacenes.isLoading && <option value="">Cargando…</option>}
              {(almacenes.data ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.nombre}
                </option>
              ))}
            </select>
          )}
        </Campo>
        <Campo etiqueta="Guía de remisión" error={e.guia}>
          {(p) => <input {...p} placeholder="Opcional" maxLength={30} value={b.guia} disabled={disabled} onChange={(ev) => poner('guia', ev.target.value.toUpperCase())} />}
        </Campo>
        <Campo etiqueta="Moneda" tipo="select">
          {(p) => (
            <select {...p} value={b.moneda} disabled={disabled} onChange={(ev) => poner('moneda', ev.target.value)}>
              <option value="PEN">Soles</option>
              <option value="USD">Dólares</option>
            </select>
          )}
        </Campo>
        {b.moneda === 'USD' && (
          <Campo etiqueta="Tipo de cambio" error={e.tipoCambio} ayuda="Vacío = el oficial del día.">
            {(p) => <input {...p} inputMode="decimal" placeholder="Ej. 3.75" value={b.tipoCambio} disabled={disabled} onChange={(ev) => poner('tipoCambio', ev.target.value)} />}
          </Campo>
        )}
      </div>
      <div className="compra-opciones">
        <label className="casilla">
          <input type="checkbox" checked={b.incluyeIgv} disabled={disabled} onChange={(ev) => poner('incluyeIgv', ev.target.checked)} />
          <span>Los precios del comprobante ya incluyen IGV</span>
        </label>
        <Campo etiqueta="Redondeo del comprobante" error={e.ajuste} ayuda="Solo si la factura trae un ajuste (hasta ±0.10).">
          {(p) => <input {...p} className="compra-corto" inputMode="decimal" placeholder="0.00" value={b.ajuste} disabled={disabled} onChange={(ev) => poner('ajuste', ev.target.value)} />}
        </Campo>
      </div>
    </>
  )
}
