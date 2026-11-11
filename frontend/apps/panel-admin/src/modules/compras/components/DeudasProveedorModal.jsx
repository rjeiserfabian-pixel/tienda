import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useListado } from '../../../shared/hooks/useListado'
import { dinero } from '../compras'
import PagarCompraModal from './PagarCompraModal'
import { TablaFacturas } from './PorFactura'

/**
 * Las deudas de un proveedor: sus facturas a crédito pendientes, cada una con su cuota más próxima,
 * para ver o pagar. Al pagar, la lista y los totales se actualizan solos.
 */
export default function DeudasProveedorModal({ proveedor, onCerrar }) {
  const navegar = useNavigate()
  const { empresaActivaId } = useEmpresas()
  const [dialogo, setDialogo] = useState(null) // { tipo: 'pagar', id }
  const consulta = useListado(['compras', 'por-pagar'], '/compras/por-pagar/', { empresa: empresaActivaId, proveedor: proveedor.proveedor, page_size: 100 }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []
  const totales = [...new Set(filas.map((f) => f.moneda))].map((moneda) => ({
    moneda,
    saldo: filas.filter((f) => f.moneda === moneda).reduce((s, f) => s + Math.round(Number(f.saldo) * 100), 0) / 100,
  }))

  return (
    <>
      <Modal titulo={proveedor.proveedor_nombre} subtitulo={`${proveedor.tipo_documento} ${proveedor.numero_documento}${proveedor.ciudad ? ` · ${proveedor.ciudad}` : ''}`} onCerrar={onCerrar} ancho={1100}>
        <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
          <p className="celda-suave" aria-live="polite">
            {filas.length === 0 ? 'Este proveedor ya no tiene deudas pendientes.' : `${filas.length} ${filas.length === 1 ? 'factura pendiente' : 'facturas pendientes'} · Total adeudado: `}
            {totales.map((t, i) => (
              <strong key={t.moneda}>
                {i > 0 ? ' + ' : ''}
                {dinero(t.saldo, t.moneda)}
              </strong>
            ))}
          </p>
          <TablaFacturas filas={filas} onVer={(id) => navegar(`/compras/registro/${id}`)} onPagar={(id) => setDialogo({ tipo: 'pagar', id })} vacio={{ titulo: 'Sin deudas pendientes', descripcion: 'Todas sus compras a crédito están pagadas.' }} />
        </EstadoConsulta>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar}>
            Cerrar
          </button>
        </div>
      </Modal>
      {dialogo?.tipo === 'pagar' && <PagarCompraModal compraId={dialogo.id} onCerrar={() => setDialogo(null)} />}
    </>
  )
}
