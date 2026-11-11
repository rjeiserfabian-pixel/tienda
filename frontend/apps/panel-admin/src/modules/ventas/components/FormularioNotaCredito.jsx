import { useNavigate } from 'react-router-dom'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { fechaCorta, hoyIso } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import { useNotaCredito } from '../hooks/useNotaCredito'
import { aDinero } from '../ventas'
import LineasNota from './LineasNota'
import ReembolsoNota from './ReembolsoNota'

/** Un dato del comprobante que se llena solo al buscar la venta (no se escribe). */
const Dato = ({ etiqueta, valor, clase }) => <Campo etiqueta={etiqueta} clase={clase}>{(p) => <input {...p} value={valor ?? ''} readOnly disabled />}</Campo>

/**
 * La nota de crédito de un comprobante ya elegido: tipo de nota, serie, sustento, qué se devuelve y
 * cómo se le devuelve el dinero al cliente. El servidor calcula los importes y revisa todo otra vez.
 */
export default function FormularioNotaCredito({ pendiente: p, medios, onBuscar }) {
  const navegar = useNavigate()
  const n = useNotaCredito(p, medios)
  const m = p.moneda
  const d = n.datos
  const monto = (campo) => (d ? dinero(d[campo], m) : '—')
  // Si parte de lo vendido vino de la otra empresa (venta interna), a quién vuelve al devolverlo.
  const devuelveA = [...new Set(p.lineas.map((l) => l.vuelve_a).filter(Boolean))]

  return (
    <form onSubmit={n.enviar} noValidate className="pos-layout">
      <div className="compra-layout">
        <div className="compra-principal">
          <PanelTarjeta icono="documento" titulo="Datos de la nota" descripcion="El tipo de nota, su serie y por qué se emite.">
            <div className="pos-bloques">
              <div className="fila-campos">
                <Campo etiqueta="Tipo de nota de crédito" tipo="select" requerido>
                  {(c) => (
                    <select {...c} value={n.motivo} disabled={n.enviando} onChange={(e) => n.cambiarMotivo(e.target.value)}>
                      {p.motivos.map((o) => (
                        <option key={o.codigo} value={o.codigo} disabled={!o.disponible}>
                          {o.nombre}
                          {o.disponible ? '' : ' (el comprobante ya tiene devoluciones)'}
                        </option>
                      ))}
                    </select>
                  )}
                </Campo>
                {p.series.length > 1 ? (
                  <Campo etiqueta="Serie · próximo N°" tipo="select" requerido>
                    {(c) => (
                      <select {...c} value={n.serie} disabled={n.enviando} onChange={(e) => n.setSerieElegida(e.target.value)}>
                        {!n.serie && <option value="">Elige la serie</option>}
                        {p.series.map((s) => (
                          <option key={s.id} value={s.id}>
                            {s.proximo}
                            {s.nombre ? ` · ${s.nombre}` : ''}
                          </option>
                        ))}
                      </select>
                    )}
                  </Campo>
                ) : (
                  <Dato etiqueta="Serie · próximo N°" valor={p.series[0]?.proximo ?? 'Sin serie'} />
                )}
                <Campo etiqueta="Fecha" icono="calendario" ayuda="Siempre la de hoy.">
                  {(c) => <input {...c} type="date" value={hoyIso()} readOnly disabled />}
                </Campo>
              </div>
              <Campo etiqueta="Sustento" requerido contador={{ actual: n.descripcion.length, max: 250 }}>
                {(c) => <input {...c} maxLength={250} placeholder="Ej. El cliente devolvió el producto por falla de fábrica" value={n.descripcion} disabled={n.enviando} onChange={(e) => n.setDescripcion(e.target.value)} />}
              </Campo>
              <label className="nota-reingreso">
                <input type="checkbox" checked={n.reingresa} disabled={n.enviando} onChange={(e) => n.setReingresa(e.target.checked)} /> Stock: el producto vuelve al almacén
                <small className="celda-suave"> Quita la marca si llegó dañado y no se puede volver a vender.</small>
              </label>
              {devuelveA.length > 0 && (
                <p className="celda-suave" role="status">
                  {n.reingresa
                    ? `Parte de esta venta salió del stock de ${devuelveA.join(' y ')}: lo que devuelvas de esos productos vuelve a su almacén, al costo con que salió.`
                    : `Parte de esta venta salió del stock de ${devuelveA.join(' y ')}: sin marcar «Stock», esa mercadería tampoco vuelve a su almacén.`}
                </p>
              )}
            </div>
          </PanelTarjeta>

          <PanelTarjeta icono="documento" titulo="Venta que se devuelve" descripcion="Los datos se llenan solos al buscar el comprobante.">
            <div className="pos-bloques">
              <div className="fila-campos">
                <button type="button" className="primario nota-buscar" disabled={n.enviando} onClick={onBuscar}>
                  <Icono nombre="buscar" tam={18} /> Buscar venta
                </button>
                <Dato etiqueta="Fecha de emisión" valor={fechaCorta(p.fecha)} />
                <Dato etiqueta="Comprobante de referencia" valor={p.tipo_nombre} />
                <Dato etiqueta="Nro." valor={p.numero_completo} />
              </div>
              <div className="fila-campos">
                <Dato etiqueta="Cliente" valor={`${p.cliente_nombre || 'Clientes varios'}${p.cliente_documento ? ` · ${p.cliente_tipo_documento} ${p.cliente_documento}` : ''}`} />
                <Dato etiqueta="Dirección" valor={p.cliente_direccion} />
              </div>
              {p.a_credito && <p className="celda-suave">Venta a crédito: lo que el cliente todavía debe ({dinero(p.saldo_por_cobrar, m)}) se descuenta primero; solo el resto se devuelve en dinero.</p>}
            </div>
          </PanelTarjeta>

          <PanelTarjeta icono="package" titulo="Productos" descripcion={n.esTotal ? 'Se devuelve todo lo que queda del comprobante.' : 'Escribe cuánto devuelve el cliente de cada producto.'}>
            <LineasNota lineas={p.lineas} editable={!n.esTotal} cantidades={n.cantidades} series={n.series} importes={n.importes} moneda={m} disabled={n.enviando} onCantidad={n.escribirCantidad} onSeries={n.elegirSeries} />
          </PanelTarjeta>

          {n.aReembolsarCts > 0 && (
            <PanelTarjeta icono="wallet" titulo="Dinero devuelto" descripcion="Por los mismos métodos con que pagó el cliente; puedes cambiarlos o dividirlos.">
              <ReembolsoNota medios={medios} cobros={n.cobros} aReembolsarCts={n.aReembolsarCts} moneda={m} disabled={n.enviando} onCobros={n.setCobros} />
            </PanelTarjeta>
          )}
        </div>

        <aside className="compra-resumen" aria-label="Resumen de la nota">
          <h3>Resumen</h3>
          {n.errorDeCalculo && (
            <p role="alert" className="compra-aviso">
              {n.errorDeCalculo}
            </p>
          )}
          <dl className="compra-totales" aria-busy={n.calculando}>
            <div>
              <dt>Op. gravada</dt>
              <dd>{monto('op_gravada')}</dd>
            </div>
            <div>
              <dt>Op. exonerada</dt>
              <dd>{monto('op_exonerada')}</dd>
            </div>
            <div>
              <dt>Op. inafecta</dt>
              <dd>{monto('op_inafecta')}</dd>
            </div>
            <div>
              <dt>IGV</dt>
              <dd>{monto('igv')}</dd>
            </div>
            <div className="compra-total">
              <dt>Total</dt>
              <dd aria-live="polite">{n.calculando ? 'Calculando…' : monto('total')}</dd>
            </div>
            {p.a_credito && n.aCuotas > 0 && (
              <div>
                <dt>Se descuenta de la deuda</dt>
                <dd>{dinero(n.aCuotas, m)}</dd>
              </div>
            )}
            <div>
              <dt>Se devuelve en dinero</dt>
              <dd>{dinero(aDinero(n.aReembolsarCts), m)}</dd>
            </div>
          </dl>
          {n.intento && n.errores.length > 0 && (
            <div className="compra-faltan">
              <strong>Para emitir falta:</strong>
              <ul>
                {[...new Set(n.errores)].map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </div>
          )}
          {n.error && (
            <p role="alert" className="campo-error">
              {n.error}
            </p>
          )}
          <button type="submit" className="primario pos-generar" disabled={!n.puedeEnviar}>
            <Icono nombre="documento" tam={20} />
            {n.enviando ? 'Emitiendo…' : 'Emitir nota de crédito'}
          </button>
          <button type="button" className="boton-cabecera" disabled={n.enviando} onClick={() => navegar('/ventas/notas-credito')}>
            Cancelar
          </button>
          <small className="celda-suave">Una nota de crédito no se puede anular. Lo devuelto vuelve al almacén al costo con que salió.</small>
        </aside>
      </div>
    </form>
  )
}
