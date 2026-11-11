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
 * Resumen que acompaña a la pantalla (queda a la vista al bajar): totales calculados por el
 * servidor, lo que aún falta para poder registrar y el botón de registrar.
 */
export default function ResumenCompra({ calculo, calculando, errorCalculo, moneda, faltan, general, enviando, onRegistrar, onCancelar, productos, unidades, totalXml, avisosPrecio = [] }) {
  return (
    <aside className="compra-resumen" aria-label="Resumen de la compra">
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
            {hayMonto(calculo.ajuste_redondeo) && (
              <div>
                <dt>Redondeo</dt>
                <dd>{dinero(calculo.ajuste_redondeo, moneda)}</dd>
              </div>
            )}
            <div className="compra-total">
              <dt>Total a pagar</dt>
              <dd>{dinero(calculo.total, moneda)}</dd>
            </div>
          </>
        ) : (
          <div className="compra-total">
            <dt>Total a pagar</dt>
            <dd>{dinero(0, moneda)}</dd>
          </div>
        )}
      </dl>
      {totalXml && calculo && (
        <p className={Math.abs(Number(calculo.total) - Number(totalXml.total)) <= 0.05 ? 'celda-suave' : 'compra-aviso'} role="status">
          {Math.abs(Number(calculo.total) - Number(totalXml.total)) <= 0.05
            ? `El total coincide con el de la factura XML (${dinero(totalXml.total, totalXml.moneda)}).`
            : `El total de la factura XML es ${dinero(totalXml.total, totalXml.moneda)} y aquí sale ${dinero(calculo.total, moneda)}. Revisa cantidades, precios y afectaciones.`}
        </p>
      )}
      {avisosPrecio.length > 0 && (
        <div className="compra-aviso" role="status">
          <strong>Precio distinto al pactado en la orden:</strong>
          <ul>
            {avisosPrecio.map((a) => (
              <li key={a.linea_orden}>
                {a.producto_nombre}: pactado {dinero(a.precio_pactado, moneda)}, facturado {dinero(a.precio_facturado, moneda)}
                {a.porcentaje ? ` (${Number(a.porcentaje) > 0 ? '+' : ''}${Number(a.porcentaje)} %)` : ''}
              </li>
            ))}
          </ul>
          <small>Se registra con el precio de tu factura. Si no es lo esperado, corrígelo o consulta con el proveedor.</small>
        </div>
      )}
      {calculo?.igv_al_costo && Number(calculo.igv) > 0 && <p className="celda-suave">El IGV de esta compra se suma al costo de los productos.</p>}
      {moneda === 'USD' && calculo && <p className="celda-suave">Tipo de cambio {calculo.tipo_cambio}. El inventario se valoriza en soles.</p>}

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
        <Icono nombre="truck" tam={20} /> {enviando ? 'Registrando…' : calculando ? 'Calculando…' : 'Registrar compra'}
      </button>
      <button type="button" disabled={enviando} onClick={onCancelar}>
        Cancelar
      </button>
    </aside>
  )
}
