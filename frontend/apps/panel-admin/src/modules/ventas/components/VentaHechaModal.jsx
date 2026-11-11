import { useNavigate } from 'react-router-dom'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { dinero } from '../../compras/compras'
import { numeroInterno } from '../ventas'
import { useImpresionTicket } from '../hooks/useImpresionTicket'

/** Lo que se ve al cobrar: los comprobantes emitidos (uno por empresa), con su ticket para imprimir. */
export default function VentaHechaModal({ venta, onNueva }) {
  const navegar = useNavigate()
  const { imprimir, portal } = useImpresionTicket(venta)
  const vuelto = venta.comprobantes.flatMap((c) => c.cobros).reduce((suma, k) => suma + Number(k.vuelto), 0)

  return (
    <Modal titulo="Venta registrada" subtitulo={`Venta N° ${numeroInterno(venta)} · ${venta.cliente_nombre}`} onCerrar={onNueva} ancho={560}>
      <ul className="pos-emitidos">
        {venta.comprobantes.map((c) => (
          <li key={c.id}>
            <div>
              <strong>
                {c.tipo_nombre} {c.numero_completo}
              </strong>
              <span className="sub-texto">
                {c.empresa_nombre} · {dinero(c.total, venta.moneda)}
              </span>
            </div>
            <button type="button" className="boton-cabecera" onClick={() => imprimir(c)}>
              <Icono nombre="documento" tam={18} /> Imprimir
            </button>
          </li>
        ))}
      </ul>
      <p className="pos-total-hecho">
        Total cobrado <strong>{dinero(venta.total, venta.moneda)}</strong>
      </p>
      {vuelto > 0 && (
        <p className="pos-vuelto" role="status">
          Entrega de vuelto: <strong>{dinero(vuelto, venta.moneda)}</strong>
        </p>
      )}
      <div className="acciones">
        <button type="button" onClick={() => navegar(`/ventas/historial/${venta.id}`)}>
          Ver la venta
        </button>
        <button type="button" className="primario" autoFocus onClick={onNueva}>
          Nueva venta
        </button>
      </div>
      {portal}
    </Modal>
  )
}
