import { Icono } from '../../../shared/components/IconosPanel'
import { dinero } from '../compras'

const FILAS = [
  ['op_gravada', 'Operación gravada'],
  ['op_ivap', 'Operación IVAP'],
  ['op_exonerada', 'Operación exonerada'],
  ['op_inafecta', 'Operación inafecta'],
]

const hayMonto = (valor) => Number(valor) !== 0

/**
 * Resumen que acompaña a la pantalla: totales calculados por el servidor, si la orden pedirá
 * aprobación por su monto, lo que falta para guardar y los botones.
 */
export default function ResumenOrden({ calculo, calculando, errorCalculo, moneda, faltan, general, enviando, productos, unidades, textoGuardar, onGuardar, onCancelar }) {
  return (
    <aside className="compra-resumen" aria-label="Resumen de la orden">
      <h3>Resumen</h3>
      <p className="celda-suave">
        {productos} {productos === 1 ? 'producto' : 'productos'} · {unidades} {unidades === 1 ? 'unidad' : 'unidades'}
      </p>
      {errorCalculo && (
        <p role="alert" className="compra-aviso">
          {errorCalculo}
        </p>
      )}
      <dl className="compra-totales" aria-busy={calculando} data-calculando={calculando || undefined}>
        {calculo ? (
          <>
            {FILAS.filter(([clave]) => hayMonto(calculo[clave])).map(([clave, texto]) => (
              <div key={clave}>
                <dt>{texto}</dt>
                <dd>{dinero(calculo[clave], moneda)}</dd>
              </div>
            ))}
            <div>
              <dt>IGV</dt>
              <dd>{dinero(calculo.igv, moneda)}</dd>
            </div>
            {hayMonto(calculo.ivap) && (
              <div>
                <dt>IVAP</dt>
                <dd>{dinero(calculo.ivap, moneda)}</dd>
              </div>
            )}
            <div className="compra-total">
              <dt>Total de la orden</dt>
              <dd>{dinero(calculo.total, moneda)}</dd>
            </div>
          </>
        ) : (
          <div className="compra-total">
            <dt>Total de la orden</dt>
            <dd>{dinero(0, moneda)}</dd>
          </div>
        )}
      </dl>
      {moneda === 'USD' && calculo && <p className="celda-suave">Equivale a {dinero(calculo.total_soles)} (tipo de cambio {calculo.tipo_cambio}).</p>}
      {calculo?.requiere_aprobacion && (
        <p className="compra-aviso" role="status">
          Por su monto (más de {dinero(calculo.monto_aprobacion)}), esta orden necesitará la aprobación de un administrador antes de emitirse.
        </p>
      )}
      {faltan.length > 0 && (
        <div className="compra-faltan">
          <strong>Para guardar falta:</strong>
          <ul>
            {faltan.map((texto) => (
              <li key={texto}>{texto}</li>
            ))}
          </ul>
        </div>
      )}
      {general && (
        <p role="alert" className="campo-error">
          {general}
        </p>
      )}
      <button type="button" className="primario compra-registrar" disabled={enviando || calculando} onClick={onGuardar}>
        <Icono nombre="checklist" tam={20} /> {enviando ? 'Guardando…' : calculando ? 'Calculando…' : textoGuardar}
      </button>
      <button type="button" disabled={enviando} onClick={onCancelar}>
        Cancelar
      </button>
    </aside>
  )
}
