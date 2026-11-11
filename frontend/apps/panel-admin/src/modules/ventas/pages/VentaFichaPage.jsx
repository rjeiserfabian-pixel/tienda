import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../../../core/api/client'
import BotonVolver from '../../../shared/components/BotonVolver'
import Can from '../../../shared/components/Can'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { cantidad, fechaCorta } from '../../almacen/inventario'
import AccionConNotaModal from '../../caja/components/AccionConNotaModal'
import { dinero } from '../../compras/compras'
import AbonarModal from '../components/AbonarModal'
import CuotasComprobante from '../components/CuotasComprobante'
import { useImpresionTicket } from '../hooks/useImpresionTicket'
import { ESTADOS_VENTA, FORMAS_PAGO, numeroInterno } from '../ventas'
import '../../almacen/inventario.css'
import '../../compras/compras.css'
import '../ventas.css'

const RUTA = '/ventas/historial'
const INVALIDAR = [['ventas'], ['caja'], ['almacen'], ['inventario'], ['stock']]

function Comprobante({ venta, c, onImprimir, onAnular, onAbonar, onAnularAbono, onDevolver, onEnviar }) {
  const m = venta.moneda
  const anulado = c.estado === 'ANULADO'
  const aCredito = venta.forma_pago === 'CREDITO'
  const debe = Number(c.saldo) > 0
  return (
    <PanelTarjeta icono="documento" titulo={`${c.tipo_nombre} ${c.numero_completo}`} descripcion={`${c.empresa_nombre} · RUC ${c.empresa_ruc} · ${fechaCorta(c.fecha)}`}>
      <div className="venta-acciones">
        {anulado && (
          <span className="pildora" data-tono="rojo">
            Anulado
          </span>
        )}
        <button type="button" className="boton-cabecera" onClick={() => onImprimir(c)}>
          <Icono nombre="documento" tam={18} /> Imprimir
        </button>
        {aCredito && !anulado && (
          <span className="pildora" data-tono={debe ? 'ambar' : 'verde'}>
            {debe ? `Por cobrar ${dinero(c.saldo, m)}` : 'Cobrado por completo'}
          </span>
        )}
        {aCredito && !anulado && debe && (
          <Can permiso="VENTAS.COBRAR">
            <button type="button" className="primario boton-cabecera" onClick={() => onAbonar(c)}>
              Cobrar cuota
            </button>
          </Can>
        )}
        {!anulado && (
          <Can permiso="VENTAS.NOTA_CREDITO">
            <button type="button" className="boton-cabecera" onClick={() => onDevolver(c)}>
              Nota de crédito
            </button>
          </Can>
        )}
        {!anulado && (
          <Can permiso="VENTAS.GUIA_REMISION">
            <button type="button" className="boton-cabecera" onClick={() => onEnviar(c)}>
              Guía de remisión
            </button>
          </Can>
        )}
        {!anulado && c.notas_credito.length === 0 && (
          <Can permiso="VENTAS.ANULAR">
            <button type="button" className="boton-cabecera peligro-suave" onClick={() => onAnular(c)}>
              Anular este comprobante
            </button>
          </Can>
        )}
      </div>
      {anulado && c.motivo_anulacion && <p className="compra-aviso">Motivo: {c.motivo_anulacion}</p>}
      {c.notas_credito.length > 0 && (
        <p className="compra-aviso">
          Notas de crédito sobre este comprobante:{' '}
          {c.notas_credito.map((n, i) => (
            <span key={n.id}>
              {i > 0 ? ' · ' : ''}
              <strong>{n.numero_completo}</strong> ({dinero(n.total, m)})
            </span>
          ))}
          . Ya no se puede anular el comprobante.
        </p>
      )}
      <div className="marco-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th>Producto</th>
              <th className="num">Cant.</th>
              <th className="num">P. unit. sin IGV</th>
              <th className="num">IGV</th>
              <th className="num">Total</th>
            </tr>
          </thead>
          <tbody>
            {c.lineas.map((l) => (
              <tr key={l.id}>
                <td className="col-texto">
                  {l.descripcion}
                  <span className="sub-texto">
                    {l.codigo} · {l.afectacion_nombre}
                    {l.series.length > 0 ? ` · Serie: ${l.series.join(', ')}` : ''}
                    {l.bajo_minimo ? ' · Vendido bajo el mínimo' : ''}
                  </span>
                </td>
                <td className="num">
                  {cantidad(l.cantidad)} {l.unidad}
                </td>
                <td className="num">{dinero(l.precio_unitario, m)}</td>
                <td className="num">{dinero(l.igv, m)}</td>
                <td className="num">{dinero(l.total, m)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="compra-totales compra-totales-ficha">
        {Number(c.op_gravada) > 0 && (
          <div>
            <dt>Operación gravada</dt>
            <dd>{dinero(c.op_gravada, m)}</dd>
          </div>
        )}
        {Number(c.op_exonerada) > 0 && (
          <div>
            <dt>Operación exonerada</dt>
            <dd>{dinero(c.op_exonerada, m)}</dd>
          </div>
        )}
        {Number(c.op_inafecta) > 0 && (
          <div>
            <dt>Operación inafecta</dt>
            <dd>{dinero(c.op_inafecta, m)}</dd>
          </div>
        )}
        <div>
          <dt>IGV</dt>
          <dd>{dinero(c.igv, m)}</dd>
        </div>
        <div className="compra-total">
          <dt>Total</dt>
          <dd>{dinero(c.total, m)}</dd>
        </div>
      </dl>
      {aCredito && c.cuotas.length > 0 && <CuotasComprobante comprobante={c} moneda={m} puedeAnular={!anulado} onAnularAbono={onAnularAbono} />}
      <h4>{aCredito ? 'Pago inicial' : 'Cobros'}</h4>
      <ul className="venta-cobros">
        {c.cobros.map((k) => (
          <li key={k.id}>
            <span>
              <strong>{k.medio_pago_nombre}</strong>
              <span className="sub-texto">
                Entró a {k.cuenta_nombre}
                {k.referencia ? ` · Op. ${k.referencia}` : ''}
                {Number(k.vuelto) > 0 ? ` · Recibido ${dinero(k.recibido, m)}, vuelto ${dinero(k.vuelto, m)}` : ''}
              </span>
            </span>
            <strong>{dinero(k.monto, m)}</strong>
          </li>
        ))}
      </ul>
    </PanelTarjeta>
  )
}

/** Ficha de una venta: sus comprobantes (uno por empresa), lo que se vendió y cómo se cobró. */
export default function VentaFichaPage() {
  const { id } = useParams()
  const navegar = useNavigate()
  const consulta = useQuery({
    queryKey: ['ventas', 'ficha', id],
    queryFn: ({ signal }) => api.get(`/ventas/${id}/`, { signal }).then((r) => r.data),
  })
  const v = consulta.data
  const { imprimir, portal } = useImpresionTicket(v)
  const [anulando, setAnulando] = useState(null) // 'venta' o el comprobante
  const [abonando, setAbonando] = useState(null)
  const [anulandoAbono, setAnulandoAbono] = useState(null)
  const estado = v && ESTADOS_VENTA[v.estado]
  const vigentes = v ? v.comprobantes.filter((c) => c.estado === 'EMITIDO').length : 0

  return (
    <main className="listado compra-pagina">
      <BotonVolver ruta={RUTA} texto="Volver al historial" />
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(v)}>
        {v && (
          <>
            <CabeceraListado icono="cart" titulo={`Venta N° ${numeroInterno(v)}`} descripcion={`${fechaCorta(v.fecha)} · ${v.cliente_nombre} · Vendió ${v.vendedor_nombre}`}>
              <span className="pildora" data-tono={estado.tono}>
                {estado.texto}
              </span>
              {vigentes > 0 && !v.parcial && (
                <Can permiso="VENTAS.ANULAR">
                  <button type="button" className="boton-cabecera peligro-suave" onClick={() => setAnulando('venta')}>
                    Anular la venta
                  </button>
                </Can>
              )}
            </CabeceraListado>
            {v.estado === 'ANULADO' && <p className="compra-aviso">Venta anulada: {v.motivo_anulacion}</p>}
            {v.ventas_internas?.map((i) => (
              <p key={i.id} className="compra-aviso" role="status">
                Venta interna N° {String(i.numero).padStart(6, '0')}: {i.entrega} le pasó la mercadería a {i.recibe}, al costo ({i.documento_nombre.toLowerCase()}), para emitir un solo comprobante.
                {i.estado === 'ANULADO' ? ' Quedó anulada con la venta: la mercadería volvió a su almacén.' : ''}
                {i.estado === 'EMITIDO' && i.devolucion === 'PARCIAL' ? ` Ya volvió a ${i.entrega} una parte, por devoluciones del cliente.` : ''}
                {i.estado === 'EMITIDO' && i.devolucion === 'TOTAL' ? ` Todo volvió a ${i.entrega}, por devoluciones del cliente.` : ''}
              </p>
            ))}
            {v.parcial && (
              <p className="compra-aviso" role="status">
                Esta venta se hizo en el mostrador de {v.mostrador_nombre}. Aquí ves solo los comprobantes de tus empresas; el total es la suma de lo que ves. Para anular toda la venta hace falta acceso a todas sus empresas.
              </p>
            )}
            <dl className="venta-datos">
              <div>
                <dt>Cliente</dt>
                <dd>
                  {v.cliente_nombre}
                  {v.cliente_documento ? ` · ${v.cliente_tipo_documento} ${v.cliente_documento}` : ''}
                </dd>
              </div>
              <div>
                <dt>Lista de precios</dt>
                <dd>{v.lista_nombre || '—'}</dd>
              </div>
              <div>
                <dt>Forma de pago</dt>
                <dd>{FORMAS_PAGO[v.forma_pago]}</dd>
              </div>
              <div>
                <dt>Moneda</dt>
                <dd>{v.moneda === 'USD' ? `Dólares · T.C. ${v.tipo_cambio}` : 'Soles'}</dd>
              </div>
              <div>
                <dt>{v.parcial ? 'Total de tus comprobantes' : 'Total de la venta'}</dt>
                <dd>
                  <strong>{dinero(v.total, v.moneda)}</strong>
                </dd>
              </div>
            </dl>
            {v.comprobantes.map((c) => (
              <Comprobante key={c.id} venta={v} c={c} onImprimir={imprimir} onAnular={setAnulando} onAbonar={setAbonando} onAnularAbono={setAnulandoAbono} onDevolver={(comprobante) => navegar(`/ventas/notas-credito/nueva?comprobante=${comprobante.id}`)} onEnviar={(comprobante) => navegar(`/ventas/guias-remision/nueva?comprobante=${comprobante.id}`)} />
            ))}
            {anulando && (
              <AccionConNotaModal
                url={anulando === 'venta' ? `/ventas/${v.id}/anular/` : `/ventas/${v.id}/comprobantes/${anulando.id}/anular/`}
                invalidar={INVALIDAR}
                titulo={anulando === 'venta' ? 'Anular la venta' : `Anular ${anulando.numero_completo}`}
                subtitulo={`Venta N° ${numeroInterno(v)}`}
                descripcion={anulando === 'venta' ? 'Se anulan todos sus comprobantes: el stock vuelve a cada almacén y el dinero sale de cada caja. La numeración no se reutiliza.' : `Se anula solo este comprobante de ${anulando.empresa_nombre}: su stock vuelve al almacén y su cobro se devuelve. Los demás de la venta siguen vigentes.`}
                campo="motivo"
                etiqueta="Motivo"
                requerido
                placeholder="Ej. El cliente devolvió el producto"
                boton="Anular"
                exito="Anulado."
                peligro
                onCerrar={() => setAnulando(null)}
              />
            )}
            {abonando && <AbonarModal comprobante={{ ...abonando, moneda: v.moneda, cuotas: abonando.cuotas }} onCerrar={() => setAbonando(null)} />}
            {anulandoAbono && (
              <AccionConNotaModal
                url={`/ventas/abonos/${anulandoAbono.id}/anular/`}
                invalidar={INVALIDAR}
                titulo="Anular el abono"
                subtitulo={`${dinero(anulandoAbono.monto, v.moneda)} · ${anulandoAbono.medio_pago_nombre}`}
                descripcion="El dinero sale de la caja y las cuotas vuelven a deber lo que habían recibido."
                campo="motivo"
                etiqueta="Motivo"
                requerido
                placeholder="Ej. Se registró con el método equivocado"
                boton="Anular abono"
                exito="Abono anulado."
                peligro
                onCerrar={() => setAnulandoAbono(null)}
              />
            )}
            {portal}
          </>
        )}
      </EstadoConsulta>
    </main>
  )
}
