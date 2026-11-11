import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../../../core/api/client'
import BotonVolver from '../../../shared/components/BotonVolver'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Can from '../../../shared/components/Can'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaHora } from '../../../shared/utils/fechas'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { cantidad as formatoCantidad, fechaCorta } from '../../almacen/inventario'
import VistaPreviaImpresion from '../../ventas/components/VistaPreviaImpresion'
import AccionOrdenModal from '../components/AccionOrdenModal'
import AnticipoModal from '../components/AnticipoModal'
import OrdenA4 from '../components/OrdenA4'
import { dinero, FORMAS_PAGO } from '../compras'
import { accionesDe, avance, enlaceCorreo, enlaceWhatsapp, ESTADOS_ORDEN, telefonoWhatsapp, textoOrden } from '../ordenes'
import '../../almacen/inventario.css'
import '../compras.css'

const RUTA = '/compras/ordenes'

function Ficha({ orden: o }) {
  const navegar = useNavigate()
  const { tiene } = usePermisos()
  const [dialogo, setDialogo] = useState(null) // 'rechazar' | 'anular' | 'cerrar' | 'imprimir' | 'anticipo'
  const puede = accionesDe(o.estado)
  const envio = ['EMITIDA', 'PARCIAL'].includes(o.estado)
  const totalAnticipado = (o.anticipos ?? []).filter((a) => a.estado === 'EMITIDO').reduce((s, a) => s + Math.round(Number(a.monto) * 100), 0) / 100
  const textoEnvio = envio ? textoOrden(o, { dinero, fechaCorta, cantidad: formatoCantidad }) : ''
  const telefono = telefonoWhatsapp(o.proveedor_datos?.telefono)
  const correo = o.proveedor_datos?.correo
  const estado = ESTADOS_ORDEN[o.estado]
  const porcentaje = avance(o)
  const clave = useClaveIdempotente({ orden: o.id, estado: o.estado })

  const emitir = useMutacion({
    mutationFn: () => api.post(`/compras/ordenes/${o.id}/emitir/`, {}, { headers: { 'Idempotency-Key': clave } }).then((r) => r.data),
    invalidar: [['compras']],
    exito: (r) => (r.estado === 'PENDIENTE' ? 'Orden enviada a aprobación.' : 'Orden emitida. Ya puedes enviarla al proveedor.'),
  })
  const aprobar = useMutacion({
    mutationFn: () => api.post(`/compras/ordenes/${o.id}/aprobar/`, {}).then((r) => r.data),
    invalidar: [['compras']],
    exito: 'Orden aprobada y emitida.',
  })
  const reabrir = useMutacion({
    mutationFn: () => api.post(`/compras/ordenes/${o.id}/reabrir/`, {}).then((r) => r.data),
    invalidar: [['compras']],
    exito: 'La orden volvió a borrador.',
  })
  const ocupado = emitir.isPending || aprobar.isPending || reabrir.isPending

  return (
    <>
      <CabeceraListado icono="checklist" titulo={`Orden ${o.codigo}`} descripcion={`${o.proveedor_nombre} · ${fechaCorta(o.fecha_emision)}`}>
        <span className="pildora" data-tono={estado.tono}>
          {estado.texto}
        </span>
        {o.atrasada && (
          <span className="pildora" data-tono="rojo">
            Atrasada
          </span>
        )}
        <button type="button" className="boton-cabecera" onClick={() => setDialogo('imprimir')}>
          <Icono nombre="documento" tam={19} /> Imprimir
        </button>
        {envio && telefono && (
          <a className="boton-cabecera" href={enlaceWhatsapp(telefono, textoEnvio)} target="_blank" rel="noopener noreferrer">
            <Icono nombre="chat" tam={19} /> WhatsApp
          </a>
        )}
        {envio && correo && (
          <a className="boton-cabecera" href={enlaceCorreo(correo, `Orden de compra ${o.codigo}`, textoEnvio)}>
            <Icono nombre="correo" tam={19} /> Correo
          </a>
        )}
        {envio && (
          <Can permiso="COMPRAS.ANTICIPAR">
            <button type="button" className="boton-cabecera" onClick={() => setDialogo('anticipo')}>
              <Icono nombre="coins" tam={19} /> Anticipo
            </button>
          </Can>
        )}
        {puede.recibir && (
          <Can permiso="COMPRAS.CREAR">
            <button type="button" className="primario boton-cabecera" onClick={() => navegar(`/compras/registro/nueva?orden=${o.id}`)}>
              <Icono nombre="truck" tam={19} /> Recibir mercadería
            </button>
          </Can>
        )}
        {puede.editar && (
          <Can permiso="ORDENES_COMPRA.EDITAR">
            <button type="button" className="boton-cabecera" onClick={() => navegar(`${RUTA}/${o.id}/editar`)}>
              <Icono nombre="lapiz" tam={19} /> Editar
            </button>
          </Can>
        )}
        {puede.emitir && (
          <Can permiso="ORDENES_COMPRA.EDITAR">
            <button type="button" className="primario boton-cabecera" disabled={ocupado} onClick={() => emitir.mutate()}>
              <Icono nombre="checklist" tam={19} /> {emitir.isPending ? 'Emitiendo…' : 'Emitir'}
            </button>
          </Can>
        )}
        {puede.aprobar && (
          <Can permiso="ORDENES_COMPRA.APROBAR">
            <button type="button" className="primario boton-cabecera" disabled={ocupado} onClick={() => aprobar.mutate()}>
              {aprobar.isPending ? 'Aprobando…' : 'Aprobar'}
            </button>
            <button type="button" className="boton-cabecera" disabled={ocupado} onClick={() => setDialogo('rechazar')}>
              Rechazar
            </button>
          </Can>
        )}
        {puede.reabrir && (
          <Can permiso="ORDENES_COMPRA.EDITAR">
            <button type="button" className="boton-cabecera" disabled={ocupado} onClick={() => reabrir.mutate()}>
              {reabrir.isPending ? 'Reabriendo…' : 'Volver a borrador'}
            </button>
          </Can>
        )}
        {puede.cerrar && (
          <Can permiso="ORDENES_COMPRA.CERRAR">
            <button type="button" className="boton-cabecera" onClick={() => setDialogo('cerrar')}>
              Cerrar con faltante
            </button>
          </Can>
        )}
        {puede.anular && (
          <Can permiso="ORDENES_COMPRA.ANULAR">
            <button type="button" className="peligro boton-cabecera" onClick={() => setDialogo('anular')}>
              <Icono nombre="apagar" tam={19} /> Anular
            </button>
          </Can>
        )}
      </CabeceraListado>

      {o.estado === 'PENDIENTE' && (
        <p role="status" className="modal-aviso">
          <strong>Por aprobar:</strong> su monto ({dinero(o.total_soles)}) pasa de {dinero(o.monto_aprobacion)}. Un administrador debe aprobarla antes de que se pueda recibir mercadería.
        </p>
      )}
      {o.estado === 'BORRADOR' && o.requiere_aprobacion && !tiene('ORDENES_COMPRA.APROBAR') && (
        <p role="status" className="modal-aviso">
          Por su monto ({dinero(o.total_soles)}), al emitirla pasará a aprobación de un administrador.
        </p>
      )}
      {o.estado === 'BORRADOR' && o.motivo_rechazo && (
        <p role="status" className="modal-aviso">
          <strong>Fue rechazada:</strong> {o.motivo_rechazo}
        </p>
      )}
      {o.estado === 'CERRADA' && (
        <p role="status" className="modal-aviso">
          <strong>Cerrada con faltante</strong> {fechaHora(o.cerrada_en)} — {o.motivo_cierre}
        </p>
      )}
      {o.estado === 'ANULADA' && (
        <p role="status" className="modal-aviso">
          <strong>Anulada</strong> {fechaHora(o.anulada_en)} — {o.motivo_anulacion}
        </p>
      )}

      <PanelTarjeta icono="documento" titulo="Datos de la orden">
        <dl className="datos-lista">
          <dt>Proveedor</dt>
          <dd>
            {o.proveedor_nombre}
            <span className="sub-texto">
              {o.proveedor_datos.tipo_documento} {o.proveedor_datos.numero_documento}
            </span>
          </dd>
          <dt>Llega a</dt>
          <dd>{o.almacen_nombre}</dd>
          <dt>Entrega esperada</dt>
          <dd>{o.fecha_entrega ? fechaCorta(o.fecha_entrega) : '—'}</dd>
          <dt>Pago pactado</dt>
          <dd>{o.forma_pago === 'CREDITO' ? `${FORMAS_PAGO.CREDITO} a ${o.plazo_dias} días` : FORMAS_PAGO.CONTADO}</dd>
          <dt>Moneda</dt>
          <dd>
            {o.moneda === 'USD' ? `Dólares americanos (tipo de cambio ${o.tipo_cambio})` : 'Soles'}
            {o.precios_incluyen_igv ? ' · precios con IGV' : ''}
          </dd>
          {o.emitida_en && (
            <>
              <dt>Emitida</dt>
              <dd>{fechaHora(o.emitida_en)}</dd>
            </>
          )}
          {o.aprobada_en && (
            <>
              <dt>Aprobada</dt>
              <dd>{fechaHora(o.aprobada_en)}</dd>
            </>
          )}
          {o.observacion && (
            <>
              <dt>Observación</dt>
              <dd>{o.observacion}</dd>
            </>
          )}
        </dl>
      </PanelTarjeta>

      <PanelTarjeta icono="package" titulo="Productos pedidos" descripcion={o.estado === 'BORRADOR' || o.estado === 'PENDIENTE' ? undefined : `Avance de la recepción: ${porcentaje} %`}>
        {!['BORRADOR', 'PENDIENTE', 'ANULADA'].includes(o.estado) && <progress className="orden-avance" value={porcentaje} max={100} aria-label={`Recibido ${porcentaje} %`} />}
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th className="centrado">#</th>
                <th>Producto</th>
                <th>Unidad</th>
                <th className="num">Pedido</th>
                <th className="num">Recibido</th>
                <th className="num">Falta</th>
                <th className="num">Precio</th>
                <th className="num">Importe</th>
              </tr>
            </thead>
            <tbody>
              {o.lineas.map((l) => (
                <tr key={l.id}>
                  <td className="centrado celda-suave">{l.orden_linea}</td>
                  <td className="col-texto">
                    {l.producto_nombre}
                    <span className="sub-texto">{l.producto_codigo}</span>
                  </td>
                  <td className="celda-suave">{l.unidad}</td>
                  <td className="num">{formatoCantidad(l.cantidad)}</td>
                  <td className="num">{formatoCantidad(l.cantidad_recibida)}</td>
                  <td className="num">{formatoCantidad(l.pendiente)}</td>
                  <td className="num">{dinero(l.precio_unitario, o.moneda)}</td>
                  <td className="num">{dinero(l.total, o.moneda)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <dl className="compra-totales" aria-label="Importes de la orden">
          {[
            ['op_gravada', 'Operación gravada'],
            ['op_exonerada', 'Operación exonerada'],
            ['op_inafecta', 'Operación inafecta'],
            ['op_ivap', 'Operación IVAP'],
            ['igv', 'IGV'],
            ['ivap', 'IVAP'],
          ]
            .filter(([clave]) => Number(o[clave]) !== 0 || clave === 'igv')
            .map(([clave, texto]) => (
              <div key={clave}>
                <dt>{texto}</dt>
                <dd>{dinero(o[clave], o.moneda)}</dd>
              </div>
            ))}
          <div className="compra-total">
            <dt>Total de la orden</dt>
            <dd>{dinero(o.total, o.moneda)}</dd>
          </div>
        </dl>
      </PanelTarjeta>

      {o.compras.length > 0 && (
        <PanelTarjeta icono="truck" titulo="Mercadería recibida" descripcion="Las compras con que se fue recibiendo esta orden.">
          <div className="marco-tabla">
            <table className="tabla-datos">
              <thead>
                <tr>
                  <th>Compra</th>
                  <th>Comprobante</th>
                  <th>Fecha</th>
                  <th className="num">Total</th>
                  <th>Estado</th>
                </tr>
              </thead>
              <tbody>
                {o.compras.map((c) => (
                  <tr key={c.id} className={c.estado === 'ANULADO' ? 'anulado' : undefined}>
                    <td>
                      <Link to={`/compras/registro/${c.id}`}>N° {String(c.numero).padStart(6, '0')}</Link>
                    </td>
                    <td>{c.comprobante}</td>
                    <td>{fechaCorta(c.fecha_emision)}</td>
                    <td className="num">{dinero(c.total, o.moneda)}</td>
                    <td>{c.estado === 'ANULADO' ? <span className="estado-pildora inactivo">Anulada</span> : <span className="estado-pildora activo">Vigente</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </PanelTarjeta>
      )}

      {(o.anticipos ?? []).length > 0 && (
        <PanelTarjeta icono="coins" titulo="Anticipos" descripcion={`Dinero adelantado al proveedor por esta orden. Anticipado y vigente: ${dinero(totalAnticipado, o.moneda)}.`}>
          <div className="marco-tabla">
            <table className="tabla-datos">
              <thead>
                <tr>
                  <th>Anticipo</th>
                  <th>Fecha</th>
                  <th className="num">Monto</th>
                  <th>Estado</th>
                </tr>
              </thead>
              <tbody>
                {o.anticipos.map((a) => (
                  <tr key={a.id} className={a.estado === 'ANULADO' ? 'anulado' : undefined}>
                    <td>
                      <Link to={`/compras/anticipos?q=${encodeURIComponent(a.codigo)}`}>{a.codigo}</Link>
                    </td>
                    <td>{fechaCorta(a.fecha)}</td>
                    <td className="num">{dinero(a.monto, o.moneda)}</td>
                    <td>{a.estado === 'ANULADO' ? <span className="estado-pildora inactivo">Anulado</span> : <span className="estado-pildora activo">Vigente</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </PanelTarjeta>
      )}

      {dialogo === 'anticipo' && (
        <AnticipoModal
          inicial={{
            proveedor: { id: o.proveedor, nombre: o.proveedor_nombre, tipo_documento: o.proveedor_datos?.tipo_documento, numero_documento: o.proveedor_datos?.numero_documento },
            moneda: o.moneda,
            orden: o.id,
            ordenCodigo: o.codigo,
          }}
          onCerrar={() => setDialogo(null)}
        />
      )}
      {['rechazar', 'anular', 'cerrar'].includes(dialogo) && <AccionOrdenModal orden={o} accion={dialogo} onCerrar={() => setDialogo(null)} />}
      {dialogo === 'imprimir' && <VistaPreviaImpresion tipo="orden-compra" titulo={`Orden de compra ${o.codigo}`} subtitulo={o.proveedor_nombre} formatos={{ A4: <OrdenA4 datos={o} /> }} onCerrar={() => setDialogo(null)} />}
    </>
  )
}

/** Ficha de una orden de compra: datos, productos con su avance de recepción y las compras con que se recibió. */
export default function OrdenCompraFichaPage() {
  const { id } = useParams()
  const consulta = useQuery({
    queryKey: ['compras', 'ordenes', 'detalle', id],
    queryFn: ({ signal }) => api.get(`/compras/ordenes/${id}/`, { signal }).then((r) => r.data),
  })
  return (
    <main className="listado">
      <BotonVolver ruta={RUTA} texto="Volver a Órdenes de compra" />
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)} vacio="La orden no existe.">
        {consulta.data && <Ficha orden={consulta.data} />}
      </EstadoConsulta>
    </main>
  )
}
