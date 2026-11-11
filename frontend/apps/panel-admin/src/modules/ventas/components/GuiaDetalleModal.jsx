import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../../core/api/client'
import Can from '../../../shared/components/Can'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { cantidad, fechaCorta } from '../../almacen/inventario'
import AccionConNotaModal from '../../caja/components/AccionConNotaModal'
import { useImpresionDocumento } from '../hooks/useImpresionDocumento'
import { datosDeTransporte, lugarConUbigeo, origenDeGuia } from '../ventas'
import GuiaImpresa from './GuiaImpresa'
import GuiaTicket from './GuiaTicket'
import '../../almacen/inventario.css'
import '../ventas.css'

/** El detalle de una guía emitida: a quién va, de dónde a dónde, quién la lleva y qué viaja (se puede imprimir o anular). */
export default function GuiaDetalleModal({ id, onCerrar }) {
  const navegar = useNavigate()
  const [anulando, setAnulando] = useState(false)
  const consulta = useQuery({
    queryKey: ['ventas', 'guia', id],
    queryFn: ({ signal }) => api.get(`/ventas/guias-remision/${id}/`, { signal }).then((r) => r.data),
  })
  const g = consulta.data
  const origen = g ? origenDeGuia(g) : null
  const { imprimir, portal } = useImpresionDocumento(g ? { tipo: 'guia', titulo: `Guía ${g.numero_completo}`, subtitulo: `${origen.etiqueta} ${origen.valor} · ${g.destinatario_nombre}`, formatos: { A4: <GuiaImpresa guia={g} />, TICKET: <GuiaTicket guia={g} /> } } : null)
  return (
    <Modal titulo={g ? `Guía ${g.numero_completo}` : 'Guía de remisión'} subtitulo={g ? `${origen.etiqueta} ${origen.valor} · ${g.destinatario_nombre}` : undefined} onCerrar={onCerrar} ancho={860}>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(g)}>
        {g && (
          <>
            {g.estado === 'ANULADO' && <p className="compra-aviso">Guía anulada: {g.motivo_anulacion}</p>}
            <dl className="venta-datos">
              <div>
                <dt>Destinatario</dt>
                <dd>
                  {g.destinatario_nombre}
                  {g.destinatario_documento ? ` · ${g.destinatario_tipo_documento} ${g.destinatario_documento}` : ''}
                </dd>
              </div>
              <div>
                <dt>Motivo · traslado</dt>
                <dd>
                  {g.motivo_nombre} · el {fechaCorta(g.fecha_traslado)}
                </dd>
              </div>
              <div>
                <dt>Punto de partida</dt>
                <dd>{lugarConUbigeo(g.punto_partida, g.ubigeo_partida_nombre)}</dd>
              </div>
              <div>
                <dt>Punto de llegada</dt>
                <dd>{lugarConUbigeo(g.punto_llegada, g.ubigeo_llegada_nombre)}</dd>
              </div>
              {g.almacen_origen_nombre && (
                <div>
                  <dt>Almacén de origen</dt>
                  <dd>{g.almacen_origen_nombre}</dd>
                </div>
              )}
              <div>
                <dt>{g.modalidad_nombre}</dt>
                <dd>
                  {datosDeTransporte(g).map(([etiqueta, valor]) => (
                    <span key={etiqueta} className="sub-texto">
                      {etiqueta}: {valor}
                    </span>
                  ))}
                </dd>
              </div>
            </dl>
            <div className="marco-tabla">
              <table className="tabla-datos">
                <thead>
                  <tr>
                    <th>Producto</th>
                    <th className="num">Cantidad</th>
                    <th className="num">Peso (kg)</th>
                  </tr>
                </thead>
                <tbody>
                  {g.lineas.map((l) => (
                    <tr key={l.id}>
                      <td className="col-texto">{l.descripcion}</td>
                      <td className="num">
                        {cantidad(l.cantidad)} {l.unidad}
                      </td>
                      <td className="num">{Number(l.peso_kg) > 0 ? Number(l.peso_kg) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="celda-suave">
              {g.bultos} bulto(s){Number(g.peso_kg) > 0 ? ` · Peso total ${Number(g.peso_kg)} kg` : ''}
              {g.observacion ? ` · ${g.observacion}` : ''} · Emitida por {g.emitida_por_nombre || '—'}
            </p>
            <div className="modal-pie">
              {g.venta && (
                <button type="button" onClick={() => navegar(`/ventas/historial/${g.venta}`)}>
                  Ver la venta
                </button>
              )}
              {g.estado === 'EMITIDO' && (
                <Can permiso="VENTAS.GUIA_REMISION">
                  <button type="button" className="peligro" onClick={() => setAnulando(true)}>
                    Anular
                  </button>
                </Can>
              )}
              <button type="button" className="primario" onClick={imprimir}>
                <Icono nombre="documento" tam={18} /> Imprimir
              </button>
            </div>
            {anulando && (
              <AccionConNotaModal
                url={`/ventas/guias-remision/${g.id}/anular/`}
                invalidar={[['ventas']]}
                titulo="Anular la guía"
                subtitulo={g.numero_completo}
                descripcion={g.traspaso ? 'El traspaso queda libre para emitir otra guía.' : 'Lo que enviaba vuelve a quedar pendiente de enviar.'}
                campo="motivo"
                etiqueta="Motivo"
                requerido
                placeholder="Ej. Se canceló el viaje"
                boton="Anular guía"
                exito="Guía anulada."
                peligro
                onCerrar={() => {
                  setAnulando(false)
                  onCerrar()
                }}
              />
            )}
            {portal}
          </>
        )}
      </EstadoConsulta>
    </Modal>
  )
}
