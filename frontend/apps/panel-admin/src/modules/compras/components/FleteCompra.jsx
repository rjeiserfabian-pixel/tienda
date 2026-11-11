import Campo from '../../../shared/components/Campo'

/**
 * Flete (transporte) pagado aparte, con el comprobante de la transportista. Siempre en soles.
 * Si va «al costo» se reparte entre los productos y sube su costo; si no, solo queda registrado.
 * No cambia el total que se le debe al proveedor.
 */
export default function FleteCompra({ flete, onFlete, comprobantes, medios, cuentasPen, resuelto, error, disabled }) {
  const poner = (campo) => (ev) => onFlete((previo) => ({ ...previo, [campo]: ev.target.value }))

  return (
    <div className="compra-flete">
      <label className="casilla">
        <input type="checkbox" checked={flete.activo} disabled={disabled} onChange={(ev) => onFlete((previo) => ({ ...previo, activo: ev.target.checked }))} />
        <span>Esta compra tuvo flete (transporte pagado aparte)</span>
      </label>
      {flete.activo && (
        <>
          <div className="fila-campos">
            <Campo etiqueta="Monto del flete (S/)" requerido>
              {(c) => <input {...c} inputMode="decimal" placeholder="0.00" value={flete.monto} disabled={disabled} onChange={poner('monto')} />}
            </Campo>
            <Campo etiqueta="Comprobante del transportista" tipo="select">
              {(c) => (
                <select {...c} value={flete.tipo} disabled={disabled} onChange={poner('tipo')}>
                  <option value="">Sin comprobante</option>
                  {comprobantes.map((t) => (
                    <option key={t.codigo} value={t.codigo}>
                      {t.nombre}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Serie">
              {(c) => <input {...c} maxLength={10} value={flete.serie} disabled={disabled} onChange={(ev) => onFlete((previo) => ({ ...previo, serie: ev.target.value.toUpperCase() }))} />}
            </Campo>
            <Campo etiqueta="Número">
              {(c) => <input {...c} maxLength={20} value={flete.numero} disabled={disabled} onChange={(ev) => onFlete((previo) => ({ ...previo, numero: ev.target.value.toUpperCase() }))} />}
            </Campo>
          </div>
          <div className="fila-campos">
            <Campo etiqueta="Pagado con" tipo="select">
              {(c) => (
                <select {...c} value={resuelto.medio} disabled={disabled} onChange={(ev) => onFlete((previo) => ({ ...previo, medio: ev.target.value, referencia: '' }))}>
                  {medios.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.nombre}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Sale de (soles)" tipo="select">
              {(c) => (
                <select {...c} value={resuelto.cuenta} disabled={disabled} onChange={poner('cuenta')}>
                  <option value="">Elija la caja o cuenta</option>
                  {cuentasPen.map((cu) => (
                    <option key={cu.id} value={cu.id}>
                      {cu.nombre}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            {resuelto.pideReferencia && (
              <Campo etiqueta="N° de operación">
                {(c) => <input {...c} maxLength={60} value={flete.referencia} disabled={disabled} onChange={poner('referencia')} />}
              </Campo>
            )}
          </div>
          <label className="casilla">
            <input type="checkbox" checked={flete.alCosto} disabled={disabled} onChange={(ev) => onFlete((previo) => ({ ...previo, alCosto: ev.target.checked }))} />
            <span>Sumar el flete al costo de los productos</span>
          </label>
          {cuentasPen.length === 0 && <p role="alert" className="compra-aviso">No hay cajas o cuentas en soles para pagar el flete.</p>}
          {error && (
            <p role="alert" className="campo-error">
              {error}
            </p>
          )}
        </>
      )}
    </div>
  )
}
