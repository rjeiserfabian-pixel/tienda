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
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { fechaHora } from '../../../shared/utils/fechas'
import { fechaCorta } from '../../almacen/inventario'
import { aNumero } from '../../almacen/utilidades'
import ActualizarPreciosModal from '../components/ActualizarPreciosModal'
import AnularCompraModal from '../components/AnularCompraModal'
import CuotasCompra from '../components/CuotasCompra'
import DetalleLineas from '../components/DetalleLineas'
import DevolucionesDeCompra from '../components/DevolucionesDeCompra'
import PagarCompraModal from '../components/PagarCompraModal'
import PagosRealizados from '../components/PagosRealizados'
import { dinero, FORMAS_PAGO, numeroInterno } from '../compras'
import '../../almacen/inventario.css'
import '../compras.css'

const RUTA = '/compras/registro'

/** Contenido de la ficha, ya con la compra cargada. */
function Ficha({ compra: c }) {
  const navegar = useNavigate()
  const { tiene } = usePermisos()
  const [dialogo, setDialogo] = useState(null) // 'pagar' | 'anular' | 'precios'
  const [marcadas, setMarcadas] = useState([]) // ids de las cuotas marcadas para pagar
  const vigente = c.estado === 'EMITIDO'
  const deuda = c.cuotas.reduce((s, q) => s + Math.round(aNumero(q.saldo) * 100), 0) / 100
  // Lo pagado sale de las cuotas: una devolución rebaja la deuda sin que eso sea un pago.
  const pagado = c.cuotas.reduce((s, q) => s + Math.round(aNumero(q.pagado) * 100), 0) / 100
  const rebajado = vigente ? Math.max(0, Math.round((Number(c.total) - pagado - deuda) * 100) / 100) : 0
  const puedePagar = tiene('COMPRAS.PAGAR') && vigente && c.forma_pago === 'CREDITO' && deuda > 0
  const puedeCambiarPrecios = tiene('MANTENIMIENTO.PRODUCTOS.CAMBIAR_PRECIO', { organizacion: true })

  return (
    <>
      <CabeceraListado icono="truck" titulo={`Compra N° ${numeroInterno(c)}`} descripcion={`${c.tipo_comprobante_nombre} ${c.comprobante} · ${FORMAS_PAGO[c.forma_pago]}`}>
        <span className={`estado-pildora ${vigente ? 'activo' : 'inactivo'}`}>{vigente ? 'Vigente' : 'Anulada'}</span>
        {vigente && puedeCambiarPrecios && (
          <button type="button" className="boton-cabecera" onClick={() => setDialogo('precios')}>
            <Icono nombre="coins" tam={19} /> Actualizar precios de venta
          </button>
        )}
        {vigente && (
          <Can permiso="COMPRAS.DEVOLVER">
            <button type="button" className="boton-cabecera" onClick={() => navegar(`${RUTA}/${c.id}/devolver`)}>
              <Icono nombre="swap" tam={19} /> Devolver mercadería
            </button>
          </Can>
        )}
        {vigente && (
          <Can permiso="COMPRAS.ANULAR">
            <button type="button" className="peligro boton-cabecera" onClick={() => setDialogo('anular')}>
              <Icono nombre="apagar" tam={19} /> Anular
            </button>
          </Can>
        )}
      </CabeceraListado>

      {!vigente && (
        <p role="status" className="modal-aviso">
          <strong>Anulada</strong> {fechaHora(c.anulado_en)} — {c.motivo_anulacion}
        </p>
      )}

      <PanelTarjeta icono="documento" titulo="Datos de la compra">
        <dl className="datos-lista">
          <dt>Proveedor</dt>
          <dd>{c.proveedor_nombre}</dd>
          <dt>Emisión</dt>
          <dd>{fechaCorta(c.fecha_emision)}</dd>
          <dt>Almacén</dt>
          <dd>{c.almacen_nombre}</dd>
          <dt>Moneda</dt>
          <dd>
            {c.moneda === 'USD' ? `Dólares americanos (tipo de cambio ${c.tipo_cambio})` : 'Soles'}
            {c.precios_incluyen_igv ? ' · precios con IGV' : ''}
          </dd>
          {c.nro_guia && (
            <>
              <dt>Guía</dt>
              <dd>{c.nro_guia}</dd>
            </>
          )}
          {Number(c.flete) > 0 && (
            <>
              <dt>Flete</dt>
              <dd>
                {dinero(c.flete)} · {c.flete_al_costo ? 'sumado al costo' : 'no sumado al costo'}
                {c.flete_comprobante_numero ? ` · ${c.flete_comprobante_serie ? `${c.flete_comprobante_serie}-` : ''}${c.flete_comprobante_numero}` : ''}
              </dd>
            </>
          )}
          {c.observacion && (
            <>
              <dt>Observación</dt>
              <dd>{c.observacion}</dd>
            </>
          )}
        </dl>
      </PanelTarjeta>

      <PanelTarjeta icono="package" titulo="Productos">
        <DetalleLineas compra={c} />
      </PanelTarjeta>

      {c.forma_pago === 'CREDITO' && (
        <PanelTarjeta icono="calendario" titulo="Cuotas" descripcion="Una cuota puede pagarse en partes: aquí ves cuánto se pagó de cada una.">
          <dl className="cxp-tarjetas" aria-label="Estado de la deuda">
            <div>
              <dt>Total de la compra</dt>
              <dd>{dinero(c.total, c.moneda)}</dd>
            </div>
            <div>
              <dt>Pagado</dt>
              <dd>{dinero(pagado, c.moneda)}</dd>
            </div>
            {rebajado > 0 && (
              <div>
                <dt>Rebajado por devoluciones</dt>
                <dd>{dinero(rebajado, c.moneda)}</dd>
              </div>
            )}
            <div data-tono={vigente && deuda > 0 ? 'ambar' : undefined}>
              <dt>Deuda</dt>
              <dd>{dinero(vigente ? deuda : 0, c.moneda)}</dd>
            </div>
          </dl>
          <CuotasCompra compra={c} seleccionables={puedePagar} marcadas={marcadas} onMarcar={setMarcadas} onPagar={() => setDialogo('pagar')} />
        </PanelTarjeta>
      )}

      <PanelTarjeta icono="wallet" titulo="Pagos realizados" descripcion="Cada pago con su método, su caja o cuenta y las cuotas que cubrió.">
        <PagosRealizados compra={c} />
      </PanelTarjeta>

      <DevolucionesDeCompra compra={c} />

      {dialogo === 'pagar' && (
        <PagarCompraModal
          compraId={c.id}
          cuotasIniciales={marcadas}
          onCerrar={() => {
            setDialogo(null)
            setMarcadas([]) // lo pagado cambió el saldo de las cuotas: se empieza de cero
          }}
        />
      )}
      {dialogo === 'anular' && <AnularCompraModal compra={c} onCerrar={() => setDialogo(null)} />}
      {dialogo === 'precios' && <ActualizarPreciosModal compra={c} onCerrar={() => setDialogo(null)} />}
    </>
  )
}

/** Ficha de una compra: datos, productos, cuotas y pagos. Desde aquí se paga, se anula o se actualizan los precios. */
export default function CompraFichaPage() {
  const { id } = useParams()
  const consulta = useQuery({
    queryKey: ['compras', 'detalle', id],
    queryFn: ({ signal }) => api.get(`/compras/${id}/`, { signal }).then((r) => r.data),
  })
  return (
    <main className="listado">
      <BotonVolver ruta={RUTA} texto="Volver a Compras" />
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)} vacio="La compra no existe.">
        {consulta.data && <Ficha compra={consulta.data} />}
      </EstadoConsulta>
    </main>
  )
}
