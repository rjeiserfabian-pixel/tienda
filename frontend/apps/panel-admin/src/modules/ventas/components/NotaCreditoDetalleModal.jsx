import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../../../core/api/client'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { fechaCorta } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import { useImpresionDocumento } from '../hooks/useImpresionDocumento'
import NotaCreditoImpresa from './NotaCreditoImpresa'
import NotaCreditoTicket from './NotaCreditoTicket'
import '../../almacen/inventario.css'
import '../ventas.css'

/** El detalle de una nota de crédito emitida: qué se devolvió, cómo y sobre qué comprobante. */
export default function NotaCreditoDetalleModal({ id, onCerrar }) {
  const navegar = useNavigate()
  const consulta = useQuery({
    queryKey: ['ventas', 'nota-credito', id],
    queryFn: ({ signal }) => api.get(`/ventas/notas-credito/${id}/`, { signal }).then((r) => r.data),
  })
  const n = consulta.data
  const { imprimir, portal } = useImpresionDocumento(n ? { tipo: 'nota-credito', titulo: `Nota de crédito ${n.numero_completo}`, subtitulo: `Sobre ${n.comprobante_numero} · ${n.cliente_nombre}`, formatos: { A4: <NotaCreditoImpresa nota={n} />, TICKET: <NotaCreditoTicket nota={n} /> } } : null)
  return (
    <Modal titulo={n ? `Nota de crédito ${n.numero_completo}` : 'Nota de crédito'} subtitulo={n ? `Sobre ${n.comprobante_numero} · ${n.cliente_nombre}` : undefined} onCerrar={onCerrar} ancho={820}>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(n)}>
        {n && (
          <>
            <p className="celda-suave">
              {fechaCorta(n.fecha)} · {n.motivo_nombre}
              {n.descripcion ? ` · ${n.descripcion}` : ''} · Emitida por {n.emitida_por_nombre || '—'}
              {n.reingresa_stock ? '' : ' · El producto no volvió al almacén'}
            </p>
            <div className="marco-tabla">
              <table className="tabla-datos">
                <thead>
                  <tr>
                    <th>Producto</th>
                    <th className="num">Cant.</th>
                    <th className="num">Importe</th>
                  </tr>
                </thead>
                <tbody>
                  {n.lineas.map((l) => (
                    <tr key={l.id}>
                      <td className="col-texto">
                        {l.descripcion}
                        {l.series.length > 0 && <span className="sub-texto">Serie: {l.series.join(', ')}</span>}
                      </td>
                      <td className="num">{l.cantidad}</td>
                      <td className="num">{dinero(l.total, n.moneda)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <dl className="compra-totales compra-totales-ficha">
              <div>
                <dt>IGV</dt>
                <dd>{dinero(n.igv, n.moneda)}</dd>
              </div>
              <div className="compra-total">
                <dt>Total</dt>
                <dd>{dinero(n.total, n.moneda)}</dd>
              </div>
              {Number(n.a_cuotas) > 0 && (
                <div>
                  <dt>Descontado de lo que debía</dt>
                  <dd>{dinero(n.a_cuotas, n.moneda)}</dd>
                </div>
              )}
              {n.reembolsos.map((r) => (
                <div key={r.id}>
                  <dt>Devuelto en {r.medio_pago_nombre}</dt>
                  <dd>{dinero(r.monto, n.moneda)}</dd>
                </div>
              ))}
            </dl>
            <div className="modal-pie">
              <button type="button" onClick={() => navegar(`/ventas/historial/${n.venta}`)}>
                Ver la venta
              </button>
              <button type="button" className="primario" onClick={imprimir}>
                <Icono nombre="documento" tam={18} /> Imprimir
              </button>
            </div>
            {portal}
          </>
        )}
      </EstadoConsulta>
    </Modal>
  )
}
