import { Icono } from '../../../shared/components/IconosPanel'
import { dinero } from '../compras'
import { MOTIVOS } from '../devoluciones'

const FILAS = [
  ['op_gravada', 'Operación gravada'],
  ['op_ivap', 'Operación IVAP'],
  ['op_exonerada', 'Operación exonerada'],
  ['op_inafecta', 'Operación inafecta'],
]

const hayMonto = (valor) => Number(valor) !== 0

/**
 * Resumen que acompaña a la pantalla: lo que vale la devolución (lo calcula el servidor), a dónde
 * va ese valor (deuda, reembolso, saldo a favor), lo que falta para registrar y el botón.
 */
export default function ResumenDevolucion({ calculo, calculando, errorCalculo, moneda, reembolsado, faltan, general, enviando, unidades, onRegistrar, onCancelar }) {
  const aDeuda = Number(calculo?.aplicado_a_deuda ?? 0)
  const porRecuperar = Number(calculo?.por_recuperar ?? 0)
  const saldo = Math.max(0, Math.round((porRecuperar - reembolsado) * 100) / 100)

  return (
    <aside className="compra-resumen" aria-label="Resumen de la devolución">
      <h3>Resumen</h3>
      <p className="celda-suave">
        {unidades} {unidades === 1 ? 'unidad' : 'unidades'} a devolver{calculo ? ` · ${MOTIVOS[calculo.motivo]}` : ''}
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
            {hayMonto(calculo.ajuste_redondeo) && (
              <div>
                <dt>Redondeo</dt>
                <dd>{dinero(calculo.ajuste_redondeo, moneda)}</dd>
              </div>
            )}
            <div className="compra-total">
              <dt>Total de la nota</dt>
              <dd>{dinero(calculo.total, moneda)}</dd>
            </div>
          </>
        ) : (
          <div className="compra-total">
            <dt>Total de la nota</dt>
            <dd>{dinero(0, moneda)}</dd>
          </div>
        )}
      </dl>

      {calculo && (
        <dl className="compra-totales" aria-label="A dónde va el valor de la nota">
          <div>
            <dt>Rebaja lo que se debe</dt>
            <dd>{dinero(aDeuda, moneda)}</dd>
          </div>
          <div>
            <dt>Dinero que vuelve</dt>
            <dd>{dinero(reembolsado, moneda)}</dd>
          </div>
          <div>
            <dt>Queda a tu favor</dt>
            <dd>{dinero(saldo, moneda)}</dd>
          </div>
        </dl>
      )}
      {calculo && <p className="celda-suave">La mercadería sale del almacén al costo con que entró en esa compra ({dinero(calculo.costo_soles)}).</p>}

      {faltan.length > 0 && (
        <div className="compra-faltan">
          <strong>Para registrar falta:</strong>
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
      <button type="button" className="primario compra-registrar" disabled={enviando || calculando} onClick={onRegistrar}>
        <Icono nombre="swap" tam={20} /> {enviando ? 'Registrando…' : calculando ? 'Calculando…' : 'Registrar devolución'}
      </button>
      <button type="button" disabled={enviando} onClick={onCancelar}>
        Cancelar
      </button>
    </aside>
  )
}
