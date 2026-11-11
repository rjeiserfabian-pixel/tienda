import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import { aNumero } from '../../almacen/utilidades'
import { dinero, resumenReparto } from '../gastos'

/**
 * Elige si el gasto es de una sola empresa o se reparte entre varias por porcentaje. El comprobante y
 * el IGV quedan en la empresa que lo registra; el reparto es el costo que cada empresa asume.
 */
export default function RepartoGasto({ activo, onActivar, reparto, onReparto, empresas, total, moneda, error, disabled, nombreEmpresa }) {
  const { suma, falta } = resumenReparto(reparto)
  const cambiar = (indice, cambios) => onReparto((previo) => previo.map((r, i) => (i === indice ? { ...r, ...cambios } : r)))
  const quitar = (indice) => onReparto((previo) => previo.filter((_, i) => i !== indice))
  const agregar = () => onReparto((previo) => [...previo, { empresa: '', porcentaje: falta > 0 ? String(falta) : '' }])
  const usadas = new Set(reparto.map((r) => r.empresa))

  return (
    <>
      <div className="segmentos" role="radiogroup" aria-label="¿De qué empresa es?">
        <button type="button" role="radio" aria-checked={!activo} className={!activo ? 'activo' : undefined} disabled={disabled} onClick={() => onActivar(false)}>
          Solo de {nombreEmpresa ?? 'esta empresa'}
        </button>
        <button type="button" role="radio" aria-checked={activo} className={activo ? 'activo' : undefined} disabled={disabled} onClick={() => onActivar(true)}>
          Repartir entre empresas
        </button>
      </div>
      {activo && (
        <div className="gasto-reparto">
          {reparto.map((r, i) => (
            <div className="gasto-reparto-fila" key={i}>
              <Campo etiqueta={i === 0 ? 'Empresa' : `Empresa ${i + 1}`} tipo="select">
                {(p) => (
                  <select {...p} value={r.empresa} disabled={disabled} onChange={(ev) => cambiar(i, { empresa: ev.target.value })}>
                    <option value="">Elija la empresa</option>
                    {empresas.map((e) => (
                      <option key={e.id} value={e.id} disabled={usadas.has(String(e.id)) && String(e.id) !== r.empresa}>
                        {e.nombre_comercial || e.razon_social}
                      </option>
                    ))}
                  </select>
                )}
              </Campo>
              <Campo etiqueta="Porcentaje (%)" clase="compra-monto">
                {(p) => <input {...p} inputMode="decimal" placeholder="50" value={r.porcentaje} disabled={disabled} onChange={(ev) => cambiar(i, { porcentaje: ev.target.value })} />}
              </Campo>
              <p className="sub-texto gasto-reparto-monto">{aNumero(r.porcentaje) > 0 && total > 0 ? dinero((total * aNumero(r.porcentaje)) / 100, moneda) : ''}</p>
              {reparto.length > 2 && (
                <button type="button" className="accion-icono peligro-suave" aria-label={`Quitar la empresa ${i + 1}`} title="Quitar" disabled={disabled} onClick={() => quitar(i)}>
                  <Icono nombre="papelera" tam={19} />
                </button>
              )}
            </div>
          ))}
          <div className="compra-pagos-pie">
            <button type="button" className="boton-cabecera" disabled={disabled || reparto.length >= empresas.length} onClick={agregar}>
              <Icono nombre="agregar" tam={19} /> Agregar empresa
            </button>
            <span className="compra-saldo" data-estado={Math.abs(suma - 100) < 0.001 ? 'ok' : 'falta'} aria-live="polite">
              {Math.abs(suma - 100) < 0.001 ? 'Suma 100%' : falta > 0 ? `Falta ${falta}%` : `Sobra ${-falta}%`}
            </span>
          </div>
          {error && (
            <p role="alert" className="campo-error">
              {error}
            </p>
          )}
          <p className="celda-suave">El comprobante y el IGV quedan en {nombreEmpresa}. Si la otra empresa debe devolver su parte, se hace con una transferencia entre empresas.</p>
        </div>
      )}
    </>
  )
}
