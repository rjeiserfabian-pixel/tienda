import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../../../core/api/client'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { fechaHora } from '../../../shared/utils/fechas'
import { cantidad, fechaCorta, ORIGENES, solesUnitario, TIPOS_MOVIMIENTO } from '../inventario'
import { soles } from '../utilidades'
import '../inventario.css'

const numero = (m) => String(m.numero).padStart(6, '0')

/** Ficha de un movimiento: datos del comprobante y cada producto con el saldo que quedó. */
export default function MovimientoDetalleModal({ id, onCerrar }) {
  const navegar = useNavigate()
  const { tiene } = usePermisos()
  const consulta = useQuery({
    queryKey: ['movimientos', 'detalle', id],
    queryFn: ({ signal }) => api.get(`/inventario/movimientos/${id}/`, { signal }).then((r) => r.data),
  })
  const m = consulta.data

  return (
    <Modal titulo={m ? `Movimiento N° ${numero(m)}` : 'Movimiento'} subtitulo={m ? `${TIPOS_MOVIMIENTO[m.tipo].texto} · ${ORIGENES[m.origen]}` : undefined} onCerrar={onCerrar} ancho={960}>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(m)}>
        {m && (
          <div className="detalle-movimiento">
            {m.estado === 'ANULADO' && (
              <p role="status" className="modal-aviso">
                <strong>Anulado</strong> {fechaHora(m.anulado_en)} — {m.motivo_anulacion}
              </p>
            )}
            {m.extorna && (
              <p role="status" className="modal-aviso">
                Es el extorno que anuló el movimiento #{m.extorna}.
              </p>
            )}
            {m.traspaso_id && (
              <p role="status" className="modal-aviso">
                Es una mitad de un traspaso entre almacenes (la otra es {m.tipo === 'SALIDA' ? 'la entrada en el almacén de destino' : 'la salida del almacén de origen'}). Al anularlo se anulan las dos.
              </p>
            )}
            <dl className="datos-lista">
              <dt>Fecha</dt>
              <dd>{fechaCorta(m.fecha)}</dd>
              <dt>Almacén</dt>
              <dd>{m.almacen_nombre}</dd>
              <dt>Comprobante</dt>
              <dd>{m.comprobante_numero ? `${m.comprobante_serie ? `${m.comprobante_serie}-` : ''}${m.comprobante_numero} (${fechaCorta(m.comprobante_fecha)})` : '—'}</dd>
              <dt>{m.cliente ? 'Cliente' : 'Proveedor'}</dt>
              <dd>{m.tercero || '—'}</dd>
              <dt>Moneda</dt>
              <dd>
                {m.moneda === 'USD' ? `Dólares (tipo de cambio ${m.tipo_cambio})` : 'Soles'}
                {Number(m.total) > 0 && ` · Total ${m.moneda === 'USD' ? 'US$' : 'S/'} ${m.total}`}
              </dd>
              <dt>Observación</dt>
              <dd>{m.observacion || '—'}</dd>
              <dt>Registrado</dt>
              <dd>{fechaHora(m.creado_en)}</dd>
            </dl>
            <div className="marco-tabla">
              <table className="tabla-datos">
                <thead>
                  <tr>
                    <th>Producto</th>
                    <th className="num">Cantidad</th>
                    <th className="num">Costo unitario</th>
                    <th className="num">Costo total</th>
                    <th className="num">Saldo</th>
                    <th className="num">Costo promedio</th>
                  </tr>
                </thead>
                <tbody>
                  {m.lineas.map((l) => (
                    <tr key={l.id}>
                      <td>
                        <strong>{l.producto_nombre}</strong>
                        <span className="sub-texto">{l.producto_codigo}</span>
                        {l.series?.length > 0 && <span className="sub-texto">Series: {(l.series_detalle ?? l.series.map((numero) => ({ numero, otros_datos: '' }))).map((s) => (s.otros_datos ? `${s.numero} (${s.otros_datos})` : s.numero)).join(', ')}</span>}
                      </td>
                      <td className="num">{cantidad(l.cantidad)} {l.unidad}</td>
                      <td className="num">{solesUnitario(l.costo_unitario)}</td>
                      <td className="num">{soles(l.costo_total)}</td>
                      <td className="num">{cantidad(l.saldo_cantidad)}</td>
                      <td className="num">{solesUnitario(l.saldo_costo_unitario)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </EstadoConsulta>
      <div className="modal-pie">
        <button type="button" onClick={onCerrar}>
          <Icono nombre="cerrar" tam={18} /> Cerrar
        </button>
        {m?.traspaso_id && m.origen === 'TRASPASO' && m.estado === 'EMITIDO' && tiene('VENTAS.GUIA_REMISION') && (
          <button type="button" className="primario" onClick={() => navegar(`/ventas/guias-remision/nueva?traspaso=${m.id}`)}>
            <Icono nombre="truck" tam={18} /> Crear guía de remisión
          </button>
        )}
      </div>
    </Modal>
  )
}
