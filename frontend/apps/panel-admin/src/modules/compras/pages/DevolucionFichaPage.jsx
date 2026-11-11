import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../../core/api/client'
import BotonVolver from '../../../shared/components/BotonVolver'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Can from '../../../shared/components/Can'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { fechaHora } from '../../../shared/utils/fechas'
import { cantidad as formatoCantidad, fechaCorta } from '../../almacen/inventario'
import AnularDevolucionModal from '../components/AnularDevolucionModal'
import { dinero, numeroInterno } from '../compras'
import { ESTADO_DEVOLUCION, MOTIVOS } from '../devoluciones'
import '../../almacen/inventario.css'
import '../compras.css'

const RUTA = '/compras/devoluciones'
const IMPORTES = [
  ['op_gravada', 'Operación gravada'],
  ['op_ivap', 'Operación IVAP'],
  ['op_exonerada', 'Operación exonerada'],
  ['op_inafecta', 'Operación inafecta'],
  ['igv', 'IGV'],
  ['ivap', 'IVAP'],
  ['ajuste_redondeo', 'Redondeo'],
]

function Ficha({ devolucion: d }) {
  const [anulando, setAnulando] = useState(false)
  const vigente = d.estado === 'EMITIDO'
  const estado = ESTADO_DEVOLUCION[d.estado]

  return (
    <>
      <CabeceraListado icono="swap" titulo={`Devolución N° ${numeroInterno(d)}`} descripcion={`Nota de crédito ${d.comprobante} · ${MOTIVOS[d.motivo]}`}>
        <span className={`estado-pildora ${estado.clase}`}>{estado.texto}</span>
        {vigente && (
          <Can permiso="COMPRAS.DEVOLUCION_ANULAR">
            <button type="button" className="peligro boton-cabecera" onClick={() => setAnulando(true)}>
              <Icono nombre="apagar" tam={19} /> Anular
            </button>
          </Can>
        )}
      </CabeceraListado>

      {!vigente && (
        <p role="status" className="modal-aviso">
          <strong>Anulada</strong> {fechaHora(d.anulado_en)} — {d.motivo_anulacion}
        </p>
      )}

      <PanelTarjeta icono="documento" titulo="Datos de la devolución">
        <dl className="datos-lista">
          <dt>Compra</dt>
          <dd>
            <Link to={`/compras/registro/${d.compra}`}>
              N° {numeroInterno({ numero: d.compra_numero })} · {d.compra_comprobante}
            </Link>
          </dd>
          <dt>Proveedor</dt>
          <dd>{d.proveedor_nombre}</dd>
          <dt>Nota de crédito</dt>
          <dd>
            {d.tipo_comprobante_codigo} {d.comprobante} · {fechaCorta(d.fecha_emision)}
          </dd>
          <dt>Almacén</dt>
          <dd>{d.almacen_nombre}</dd>
          <dt>Moneda</dt>
          <dd>{d.moneda === 'USD' ? `Dólares americanos (tipo de cambio ${d.tipo_cambio})` : 'Soles'}</dd>
          <dt>Por qué se devolvió</dt>
          <dd>{d.razon}</dd>
        </dl>
      </PanelTarjeta>

      <PanelTarjeta icono="package" titulo="Productos devueltos" descripcion="Salieron del almacén al costo con que entraron en la compra.">
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Producto</th>
                <th className="num">Cantidad</th>
                <th className="num">Valor</th>
                <th className="num">IGV</th>
                <th className="num">Total</th>
                <th className="num">Costo (S/)</th>
              </tr>
            </thead>
            <tbody>
              {d.lineas.map((l) => (
                <tr key={l.id}>
                  <td className="col-texto">
                    {l.producto_nombre}
                    {l.series.length > 0 && <span className="sub-texto">Series: {l.series.join(', ')}</span>}
                  </td>
                  <td className="num">
                    {formatoCantidad(l.cantidad)} {l.unidad}
                  </td>
                  <td className="num">{dinero(l.valor_venta, d.moneda)}</td>
                  <td className="num">{dinero(l.impuesto, d.moneda)}</td>
                  <td className="num">{dinero(l.total, d.moneda)}</td>
                  <td className="num">{dinero(l.costo_soles)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <dl className="compra-totales" aria-label="Importes de la devolución">
          {IMPORTES.filter(([clave]) => Number(d[clave]) !== 0 || clave === 'igv').map(([clave, texto]) => (
            <div key={clave}>
              <dt>{texto}</dt>
              <dd>{dinero(d[clave], d.moneda)}</dd>
            </div>
          ))}
          <div className="compra-total">
            <dt>Total de la nota</dt>
            <dd>{dinero(d.total, d.moneda)}</dd>
          </div>
        </dl>
      </PanelTarjeta>

      <PanelTarjeta icono="wallet" titulo="A dónde fue el valor de la nota">
        <dl className="cxp-tarjetas" aria-label="Destino del valor">
          <div>
            <dt>Rebajó la deuda</dt>
            <dd>{dinero(d.aplicado_a_deuda, d.moneda)}</dd>
          </div>
          <div>
            <dt>Dinero que volvió</dt>
            <dd>{dinero(d.reembolsado, d.moneda)}</dd>
          </div>
          <div data-tono={Number(d.saldo_a_favor) > 0 && vigente ? 'ambar' : undefined}>
            <dt>Saldo a favor</dt>
            <dd>{dinero(d.saldo_a_favor, d.moneda)}</dd>
          </div>
        </dl>
        {d.aplicaciones.length > 0 && (
          <p className="celda-suave">
            Cuotas rebajadas: {d.aplicaciones.map((a) => `cuota ${a.cuota_numero} (${dinero(a.monto, d.moneda)})`).join(', ')}.
          </p>
        )}
        {d.reembolsos.length > 0 && (
          <div className="marco-tabla">
            <table className="tabla-datos">
              <caption className="sr-only">Reembolsos recibidos</caption>
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>Método</th>
                  <th>Entró a</th>
                  <th className="num">Monto</th>
                  <th>Operación</th>
                  <th>Estado</th>
                </tr>
              </thead>
              <tbody>
                {d.reembolsos.map((r) => (
                  <tr key={r.id} className={r.anulado ? 'anulado' : undefined}>
                    <td>{fechaCorta(r.fecha)}</td>
                    <td>{r.medio_pago_nombre}</td>
                    <td>{r.cuenta_nombre}</td>
                    <td className="num">
                      {dinero(r.monto, d.moneda)}
                      {r.monto_cuenta && <span className="sub-texto">{dinero(r.monto_cuenta, r.moneda_cuenta)} a {r.tipo_cambio}</span>}
                    </td>
                    <td className="celda-suave">{r.referencia || '—'}</td>
                    <td>{r.anulado ? <span className="estado-pildora inactivo">Anulado</span> : <span className="estado-pildora activo">Recibido</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {d.credito && !d.credito.anulado && (
          <p className="celda-suave">
            Saldo a favor con el proveedor: disponible {dinero(d.credito.disponible, d.moneda)} de {dinero(d.credito.monto, d.moneda)}. <Link to="/compras/saldos-a-favor">Ver saldos a favor</Link>
          </p>
        )}
      </PanelTarjeta>

      {anulando && <AnularDevolucionModal devolucion={d} onCerrar={() => setAnulando(false)} />}
    </>
  )
}

/** Ficha de una devolución: la nota, lo devuelto y a dónde fue el dinero. Desde aquí se anula. */
export default function DevolucionFichaPage() {
  const { id } = useParams()
  const consulta = useQuery({
    queryKey: ['compras', 'devoluciones', 'detalle', id],
    queryFn: ({ signal }) => api.get(`/compras/devoluciones/${id}/`, { signal }).then((r) => r.data),
  })
  return (
    <main className="listado">
      <BotonVolver ruta={RUTA} texto="Volver a Devoluciones" />
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)} vacio="La devolución no existe.">
        {consulta.data && <Ficha devolucion={consulta.data} />}
      </EstadoConsulta>
    </main>
  )
}
