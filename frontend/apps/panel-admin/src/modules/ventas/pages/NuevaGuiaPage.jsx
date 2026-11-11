import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../../../core/api/client'
import BotonVolver from '../../../shared/components/BotonVolver'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import BuscarComprobanteModal from '../components/BuscarComprobanteModal'
import FormularioGuia from '../components/FormularioGuia'
import FormularioGuiaTraslado from '../components/FormularioGuiaTraslado'
import '../../almacen/inventario.css'
import '../../compras/compras.css'
import '../ventas.css'

const RUTA = '/ventas/guias-remision'

/**
 * Registrar una guía de remisión: se busca el comprobante del que sale la mercadería (o llega en
 * `?comprobante=ID` desde la ficha de la venta) y se llena el resto: destinatario, de dónde a dónde,
 * quién lo lleva, qué productos y cuántos kilos. Con `?traspaso=ID` (desde Movimientos) la guía es la de un
 * traspaso entre almacenes: la mercadería y los almacenes ya vienen del traspaso.
 */
export default function NuevaGuiaPage() {
  const { empresaActivaId, empresaActiva } = useEmpresas()
  const [parametros, setParametros] = useSearchParams()
  const navegar = useNavigate()
  const traspasoId = Number(parametros.get('traspaso')) || null
  const comprobanteId = traspasoId ? null : Number(parametros.get('comprobante')) || null
  const [buscando, setBuscando] = useState(!comprobanteId && !traspasoId)
  const envio = useQuery({
    queryKey: ['ventas', 'envio', comprobanteId],
    queryFn: ({ signal }) => api.get(`/ventas/comprobantes/${comprobanteId}/envio/`, { signal }).then((r) => r.data),
    enabled: Boolean(comprobanteId),
    staleTime: 0,
  })
  const traslado = useQuery({
    queryKey: ['ventas', 'envio-traslado', traspasoId],
    queryFn: ({ signal }) => api.get(`/ventas/traspasos/${traspasoId}/envio/`, { signal }).then((r) => r.data),
    enabled: Boolean(traspasoId),
    staleTime: 0,
  })
  const elegir = (id) => {
    setParametros({ comprobante: String(id) })
    setBuscando(false)
  }

  return (
    <main className="listado pos-pagina">
      <BotonVolver ruta={traspasoId ? '/almacen/movimientos' : RUTA} texto={traspasoId ? 'Volver a Movimientos' : 'Volver a Guías de remisión'} />
      <CabeceraListado icono="truck" titulo="Registrar guía de remisión" descripcion={`Guía de ${empresaActiva?.nombre_comercial || empresaActiva?.razon_social || 'la empresa activa'}. ${traspasoId ? 'Acompaña la mercadería de un traspaso entre almacenes' : 'Acompaña la mercadería de un comprobante ya emitido'}; no mueve stock.`} />
      {!comprobanteId && !traspasoId && (
        <PanelTarjeta icono="documento" titulo="Venta de la que sale" descripcion="Busca el comprobante de lo que se envía.">
          <button type="button" className="primario" onClick={() => setBuscando(true)}>
            <Icono nombre="buscar" tam={18} /> Buscar venta
          </button>
        </PanelTarjeta>
      )}
      {traspasoId && (
        <EstadoConsulta consulta={traslado} hayDatos={Boolean(traslado.data)}>
          {traslado.data && (traslado.data.se_puede_enviar ? (
            <FormularioGuiaTraslado key={traspasoId} envio={traslado.data} />
          ) : (
            <>
              <p className="compra-aviso">{traslado.data.anulado ? 'Este traspaso está anulado: no admite guías.' : `Este traspaso ya tiene la guía ${traslado.data.guia_vigente.numero_completo}. Si debe emitir otra, primero anule esa guía.`}</p>
              <button type="button" className="primario" onClick={() => navegar(RUTA)}>
                Ver las guías de remisión
              </button>
            </>
          ))}
        </EstadoConsulta>
      )}
      {comprobanteId && (
        <EstadoConsulta consulta={envio} hayDatos={Boolean(envio.data)}>
          {envio.data && (envio.data.se_puede_enviar ? (
            <FormularioGuia key={comprobanteId} envio={envio.data} onBuscar={() => setBuscando(true)} />
          ) : (
            <>
              <p className="compra-aviso">{envio.data.anulado ? 'Este comprobante está anulado: no admite guías.' : 'Este comprobante ya se envió por completo.'}</p>
              <button type="button" className="primario" onClick={() => setBuscando(true)}>
                <Icono nombre="buscar" tam={18} /> Buscar otra venta
              </button>
            </>
          ))}
        </EstadoConsulta>
      )}
      {buscando && <BuscarComprobanteModal empresaId={empresaActivaId} url="/ventas/comprobantes/enviables/" texto="Solo aparecen los vigentes con algo por enviar." onElegir={elegir} onCerrar={() => setBuscando(false)} />}
    </main>
  )
}
