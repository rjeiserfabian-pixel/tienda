import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../../../core/api/client'
import BotonVolver from '../../../shared/components/BotonVolver'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import BuscarComprobanteModal from '../components/BuscarComprobanteModal'
import FormularioNotaCredito from '../components/FormularioNotaCredito'
import '../../almacen/inventario.css'
import '../../compras/compras.css'
import '../ventas.css'

const RUTA = '/ventas/notas-credito'
const VACIO = []

/**
 * Emitir una nota de crédito: se busca el comprobante que se devuelve (o llega en `?comprobante=ID`
 * desde la ficha de la venta) y se llena el resto como en un formulario: tipo de nota, serie, sustento,
 * productos y dinero devuelto.
 */
export default function NuevaNotaCreditoPage() {
  const { empresaActivaId, empresaActiva } = useEmpresas()
  const [parametros, setParametros] = useSearchParams()
  const comprobanteId = Number(parametros.get('comprobante')) || null
  const [buscando, setBuscando] = useState(!comprobanteId)
  const medios = useOpciones('/mantenimiento/medios-pago/').data ?? VACIO
  const pendiente = useQuery({
    queryKey: ['ventas', 'devolucion', comprobanteId],
    queryFn: ({ signal }) => api.get(`/ventas/comprobantes/${comprobanteId}/devolucion/`, { signal }).then((r) => r.data),
    enabled: Boolean(comprobanteId),
    staleTime: 0,
  })
  const elegir = (id) => {
    setParametros({ comprobante: String(id) })
    setBuscando(false)
  }

  return (
    <main className="listado pos-pagina">
      <BotonVolver ruta={RUTA} texto="Volver a Notas de crédito" />
      <CabeceraListado icono="receipt" titulo="Emitir nota de crédito" descripcion={`Devolución a un cliente de ${empresaActiva?.nombre_comercial || empresaActiva?.razon_social || 'la empresa activa'}. Se hace sobre un comprobante ya emitido.`} />
      {!comprobanteId && (
        <PanelTarjeta icono="documento" titulo="Venta que se devuelve" descripcion="Busca el comprobante al que se le hará la nota.">
          <button type="button" className="primario" onClick={() => setBuscando(true)}>
            <Icono nombre="buscar" tam={18} /> Buscar venta
          </button>
        </PanelTarjeta>
      )}
      {comprobanteId && (
        <EstadoConsulta consulta={pendiente} hayDatos={Boolean(pendiente.data)}>
          {pendiente.data && <FormularioNotaCredito key={comprobanteId} pendiente={pendiente.data} medios={medios} onBuscar={() => setBuscando(true)} />}
        </EstadoConsulta>
      )}
      {buscando && <BuscarComprobanteModal empresaId={empresaActivaId} onElegir={elegir} onCerrar={() => setBuscando(false)} />}
    </main>
  )
}
