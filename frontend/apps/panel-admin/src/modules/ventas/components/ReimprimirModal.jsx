import { useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { dinero } from '../../compras/compras'
import { useImpresionTicket } from '../hooks/useImpresionTicket'
import { numeroInterno } from '../ventas'

/** Vuelve a imprimir los tickets de una venta ya registrada: uno por cada comprobante (empresa). */
export default function ReimprimirModal({ ventaId, onCerrar }) {
  const consulta = useQuery({
    queryKey: ['ventas', 'ficha', String(ventaId)],
    queryFn: ({ signal }) => api.get(`/ventas/${ventaId}/`, { signal }).then((r) => r.data),
  })
  const venta = consulta.data
  const { imprimir, portal } = useImpresionTicket(venta)

  return (
    <Modal titulo="Reimprimir comprobantes" subtitulo={venta ? `Venta N° ${numeroInterno(venta)} · ${venta.cliente_nombre}` : undefined} onCerrar={onCerrar} ancho={560}>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(venta)}>
        {venta && (
          <>
            <ul className="pos-emitidos">
              {venta.comprobantes.map((c) => (
                <li key={c.id}>
                  <div>
                    <strong>
                      {c.tipo_nombre} {c.numero_completo}
                    </strong>
                    <span className="sub-texto">
                      {c.empresa_nombre} · {dinero(c.total, venta.moneda)}
                      {c.estado === 'ANULADO' ? ' · ANULADO' : ''}
                    </span>
                  </div>
                  <button type="button" className="boton-cabecera" onClick={() => imprimir(c)}>
                    <Icono nombre="documento" tam={18} /> Imprimir
                  </button>
                </li>
              ))}
            </ul>
            <p className="celda-suave">Imprime uno por vez: cada comprobante sale en su propio ticket.</p>
            <div className="acciones">
              <button type="button" className="primario" autoFocus onClick={onCerrar}>
                Cerrar
              </button>
            </div>
            {portal}
          </>
        )}
      </EstadoConsulta>
    </Modal>
  )
}
