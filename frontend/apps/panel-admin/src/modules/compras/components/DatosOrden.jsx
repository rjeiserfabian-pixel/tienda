import Campo from '../../../shared/components/Campo'
import { hoyIso } from '../../almacen/inventario'

/** Cabecera de la orden: almacén de destino, fechas, moneda, cómo vienen escritos los precios y condición de pago. */
export default function DatosOrden({ b, poner, almacenes, almacen, e, disabled }) {
  return (
    <>
      <div className="fila-campos">
        <Campo etiqueta="Almacén de destino" tipo="select" requerido error={e.almacen}>
          {(p) => (
            <select {...p} value={almacen} disabled={disabled} onChange={(ev) => poner('almacen', ev.target.value)}>
              {almacenes.isLoading && <option value="">Cargando…</option>}
              {(almacenes.data ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.nombre}
                </option>
              ))}
            </select>
          )}
        </Campo>
        <Campo etiqueta="Fecha de la orden" icono="calendario" requerido error={e.fecha}>
          {(p) => <input {...p} type="date" max={hoyIso()} value={b.fecha} disabled={disabled} onChange={(ev) => poner('fecha', ev.target.value)} />}
        </Campo>
        <Campo etiqueta="Entrega esperada" icono="calendario" error={e.entrega} ayuda="Opcional. Sirve para saber qué órdenes se atrasan.">
          {(p) => <input {...p} type="date" min={b.fecha} value={b.entrega} disabled={disabled} onChange={(ev) => poner('entrega', ev.target.value)} />}
        </Campo>
      </div>
      <div className="fila-campos">
        <Campo etiqueta="Moneda" tipo="select">
          {(p) => (
            <select {...p} value={b.moneda} disabled={disabled} onChange={(ev) => poner('moneda', ev.target.value)}>
              <option value="PEN">Soles</option>
              <option value="USD">Dólares</option>
            </select>
          )}
        </Campo>
        {b.moneda === 'USD' && (
          <Campo etiqueta="Tipo de cambio" error={e.tipoCambio} ayuda="Vacío = el del día.">
            {(p) => <input {...p} inputMode="decimal" placeholder="3.75" value={b.tipoCambio} disabled={disabled} onChange={(ev) => poner('tipoCambio', ev.target.value)} />}
          </Campo>
        )}
        <Campo etiqueta="Los precios" tipo="select">
          {(p) => (
            <select {...p} value={b.incluyeIgv ? 'CON' : 'SIN'} disabled={disabled} onChange={(ev) => poner('incluyeIgv', ev.target.value === 'CON')}>
              <option value="SIN">No incluyen IGV</option>
              <option value="CON">Incluyen IGV</option>
            </select>
          )}
        </Campo>
        <Campo etiqueta="Forma de pago pactada" tipo="select">
          {(p) => (
            <select {...p} value={b.forma} disabled={disabled} onChange={(ev) => poner('forma', ev.target.value)}>
              <option value="CONTADO">Contado</option>
              <option value="CREDITO">Crédito</option>
            </select>
          )}
        </Campo>
        {b.forma === 'CREDITO' && (
          <Campo etiqueta="Plazo (días)" requerido error={e.plazo}>
            {(p) => <input {...p} inputMode="numeric" maxLength={3} value={b.plazo} disabled={disabled} onChange={(ev) => poner('plazo', ev.target.value.replace(/\D/g, ''))} />}
          </Campo>
        )}
      </div>
    </>
  )
}
