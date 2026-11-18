import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import Can from '../../../shared/components/Can'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import { fechaCorta } from '../../almacen/inventario'
import '../../compras/compras.css'
import '../garantias.css'

const RESOLUCIONES = {
  REPARADO: 'Reparado',
  CAMBIADO: 'Cambiado por otra unidad',
  NOTA_CREDITO: 'Devolución con nota de crédito',
  RECHAZADO: 'Rechazado',
}
const SIN_DATOS = []

const TONO = { ABIERTO: 'ambar', EN_SERVICIO: 'ambar', EN_PROVEEDOR: 'ambar', RESUELTO: 'verde', RECHAZADO: 'gris' }

export function EstadoReclamo({ reclamo }) {
  return (
    <span className="pildora" data-tono={TONO[reclamo.estado]}>
      {reclamo.estado_texto}
    </span>
  )
}

/** Una acción del reclamo: llama al servidor y refresca la ficha. */
function useAccion(reclamoId, ruta, exito, alExito) {
  return useMutacion({
    mutationFn: (cuerpo) => api.post(`/garantias/reclamos/${reclamoId}/${ruta}/`, cuerpo).then((r) => r.data),
    invalidar: [['garantias'], ['almacen'], ['inventario']],
    exito,
    alExito,
  })
}

function Servicio({ reclamo, onCambio }) {
  const [texto, setTexto] = useState('')
  const q = useDebounce(texto, 400)
  const ordenes = useQuery({
    queryKey: ['garantias', 'ordenes-servicio', reclamo.empresa, q],
    queryFn: ({ signal }) => api.get('/servicio-tecnico/ordenes/', { params: { empresa: reclamo.empresa, q, page_size: 8 }, signal }).then((r) => r.data.results),
    enabled: q.trim().length >= 2,
  })
  const vincular = useAccion(reclamo.id, 'servicio', 'Orden de servicio ligada.', onCambio)
  return (
    <section>
      <h3>Servicio Técnico</h3>
      {reclamo.orden_servicio_codigo ? (
        <p>
          Ligado a la orden <strong>{reclamo.orden_servicio_codigo}</strong>.
        </p>
      ) : (
        <>
          <Campo etiqueta="Buscar la orden" ayuda="Escribe el cliente, la serie del equipo o el número de orden (OS-000123).">
            {(props) => <input {...props} value={texto} onChange={(e) => setTexto(e.target.value)} />}
          </Campo>
          {ordenes.data?.length === 0 && <p className="celda-suave">No hay órdenes con ese dato.</p>}
          <ul className="lista-simple">
            {(ordenes.data ?? SIN_DATOS).map((o) => (
              <li key={o.id}>
                <button type="button" disabled={vincular.isPending} onClick={() => vincular.mutate({ orden: o.id })}>
                  {o.codigo} · {o.cliente_nombre} · {o.equipo_descripcion}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

function Proveedor({ reclamo, onCambio }) {
  const proveedores = useOpciones('/mantenimiento/proveedores/', {}).data ?? SIN_DATOS
  const [proveedor, setProveedor] = useState('')
  const [rma, setRma] = useState('')
  const [respuesta, setRespuesta] = useState('')
  const enviar = useAccion(reclamo.id, 'proveedor', 'Anotado: enviado al proveedor.', onCambio)
  const responder = useAccion(reclamo.id, 'respuesta-proveedor', 'Respuesta del proveedor anotada.', () => {
    setRespuesta('')
    onCambio?.()
  })
  return (
    <section>
      <h3>Proveedor (RMA)</h3>
      {reclamo.proveedor ? (
        <>
          <p>
            Enviado a <strong>{reclamo.proveedor_nombre}</strong> el {fechaCorta(reclamo.enviado_proveedor_el)}
            {reclamo.rma_numero ? ` · RMA ${reclamo.rma_numero}` : ''}.
          </p>
          {reclamo.respuesta_proveedor && (
            <p>
              <strong>Respuesta ({fechaCorta(reclamo.respondido_proveedor_el)}):</strong> {reclamo.respuesta_proveedor}
            </p>
          )}
          <Campo etiqueta="Anotar la respuesta del proveedor">
            {(props) => <input {...props} maxLength={500} value={respuesta} onChange={(e) => setRespuesta(e.target.value)} />}
          </Campo>
          <button type="button" disabled={responder.isPending || respuesta.trim().length < 3} onClick={() => responder.mutate({ texto: respuesta })}>
            Guardar respuesta
          </button>
        </>
      ) : (
        <>
          <Campo etiqueta="Proveedor" tipo="select">
            {(props) => (
              <select {...props} value={proveedor} onChange={(e) => setProveedor(e.target.value)}>
                <option value="">Elige un proveedor…</option>
                {proveedores.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.nombre}
                  </option>
                ))}
              </select>
            )}
          </Campo>
          <Campo etiqueta="Número de RMA (opcional)">
            {(props) => <input {...props} maxLength={40} value={rma} onChange={(e) => setRma(e.target.value)} />}
          </Campo>
          <button type="button" disabled={enviar.isPending || !proveedor} onClick={() => enviar.mutate({ proveedor, rma_numero: rma })}>
            Enviar al proveedor
          </button>
        </>
      )}
    </section>
  )
}

function Resolver({ reclamo, onCambio }) {
  const almacenes = useOpciones('/mantenimiento/almacenes/', { empresa: reclamo.empresa }).data ?? SIN_DATOS
  const [resolucion, setResolucion] = useState('REPARADO')
  const [detalle, setDetalle] = useState('')
  const [almacen, setAlmacen] = useState('')
  const [series, setSeries] = useState('')
  const [error, setError] = useState('')
  const lleva = Boolean(reclamo.numero_serie)
  const resolver = useAccion(reclamo.id, 'resolver', 'Reclamo resuelto.', onCambio)

  const enviar = (evento) => {
    evento.preventDefault()
    setError('')
    const cuerpo = { resolucion, detalle }
    if (resolucion === 'CAMBIADO') {
      if (!almacen) return setError('Elige de qué almacén sale la unidad de reemplazo.')
      cuerpo.almacen = almacen
      cuerpo.series = lleva ? series.split(/[\n,;]+/).map((s) => s.trim()).filter(Boolean) : []
    }
    resolver.mutate(cuerpo, { onError: (e) => setError(mensajeDeError(e)) })
  }

  return (
    <form onSubmit={enviar} noValidate>
      <h3>Resolver</h3>
      <Campo etiqueta="¿Cómo se resolvió?" tipo="select">
        {(props) => (
          <select {...props} value={resolucion} onChange={(e) => setResolucion(e.target.value)}>
            {Object.entries(RESOLUCIONES).map(([valor, texto]) => (
              <option key={valor} value={valor}>
                {texto}
              </option>
            ))}
          </select>
        )}
      </Campo>
      {resolucion === 'CAMBIADO' && (
        <>
          <p className="celda-suave">
            La unidad nueva sale del almacén al costo y conserva el plazo de garantía que le quedaba a la anterior. La unidad defectuosa no vuelve al stock.
          </p>
          <Campo etiqueta="Almacén del que sale" tipo="select" requerido>
            {(props) => (
              <select {...props} value={almacen} onChange={(e) => setAlmacen(e.target.value)}>
                <option value="">Elige un almacén…</option>
                {almacenes.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.nombre}
                  </option>
                ))}
              </select>
            )}
          </Campo>
          {lleva && (
            <Campo etiqueta="Serie o IMEI de la unidad que se entrega" requerido>
              {(props) => <input {...props} value={series} onChange={(e) => setSeries(e.target.value)} />}
            </Campo>
          )}
        </>
      )}
      <Campo etiqueta={resolucion === 'REPARADO' ? 'Detalle (opcional)' : resolucion === 'NOTA_CREDITO' ? 'Número de la nota de crédito' : 'Detalle'} requerido={resolucion !== 'REPARADO'}>
        {(props) => <input {...props} maxLength={500} value={detalle} onChange={(e) => setDetalle(e.target.value)} />}
      </Campo>
      {resolucion === 'NOTA_CREDITO' && <p className="celda-suave">La nota de crédito se emite en Ventas → Notas de crédito; aquí solo se anota.</p>}
      {error && (
        <p role="alert" className="campo-error">
          {error}
        </p>
      )}
      <div className="acciones">
        <button type="submit" className="primario" disabled={resolver.isPending}>
          {resolver.isPending ? 'Guardando…' : 'Cerrar el reclamo'}
        </button>
      </div>
    </form>
  )
}

/** La ficha de un reclamo: su historia, el seguimiento y cómo se resuelve. */
export default function ReclamoModal({ id, onCerrar }) {
  const consulta = useQuery({
    queryKey: ['garantias', 'reclamo', id],
    queryFn: ({ signal }) => api.get(`/garantias/reclamos/${id}/`, { signal }).then((r) => r.data),
  })
  const r = consulta.data
  const refrescar = () => consulta.refetch()
  return (
    <Modal titulo={r ? `Reclamo ${r.numero_completo}` : 'Reclamo de garantía'} subtitulo={r ? `${r.producto_nombre}${r.numero_serie ? ` · ${r.numero_serie}` : ''}` : undefined} onCerrar={onCerrar} ancho={760}>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(r)}>
        {r && (
          <>
            <dl className="cxp-tarjetas" aria-label="Resumen del reclamo">
              <div>
                <dt>Estado</dt>
                <dd>
                  <EstadoReclamo reclamo={r} />
                </dd>
                <small>Abierto el {fechaCorta(r.fecha)}</small>
              </div>
              <div>
                <dt>Cliente</dt>
                <dd>{r.cliente_nombre || 'Sin cliente'}</dd>
                <small>{r.cliente_documento}</small>
              </div>
              <div>
                <dt>Comprobante</dt>
                <dd>{r.comprobante_numero}</dd>
                <small>Garantía hasta {fechaCorta(r.garantia_vence_el)}</small>
              </div>
            </dl>
            <p>
              <strong>Falla:</strong> {r.descripcion}
              {!r.numero_serie && Number(r.cantidad) !== 1 ? ` (${Number(r.cantidad)} unidades)` : ''}
            </p>
            {r.resolucion && (
              <p>
                <strong>Resolución ({fechaCorta(r.resuelto_el)}):</strong> {r.resolucion_texto}
                {r.resolucion_detalle ? ` — ${r.resolucion_detalle}` : ''}
                {r.garantia_nueva_serie || r.garantia_nueva_vence_el ? ` · Nueva garantía${r.garantia_nueva_serie ? ` de ${r.garantia_nueva_serie}` : ''} hasta ${fechaCorta(r.garantia_nueva_vence_el)}` : ''}
              </p>
            )}
            {(r.orden_servicio || r.proveedor) && !r.resolucion && (
              <p className="celda-suave">
                {r.orden_servicio_codigo ? `Orden de servicio ${r.orden_servicio_codigo}. ` : ''}
                {r.proveedor_nombre ? `Con el proveedor ${r.proveedor_nombre}.` : ''}
              </p>
            )}
            {(r.estado === 'ABIERTO' || r.estado === 'EN_SERVICIO' || r.estado === 'EN_PROVEEDOR') && (
              <>
                <Can permiso="VENTAS.GARANTIA_RECLAMAR">
                  <Servicio reclamo={r} onCambio={refrescar} />
                  <Proveedor reclamo={r} onCambio={refrescar} />
                </Can>
                <Can permiso="VENTAS.GARANTIA_RESOLVER">
                  <Resolver reclamo={r} onCambio={refrescar} />
                </Can>
              </>
            )}
          </>
        )}
      </EstadoConsulta>
    </Modal>
  )
}
