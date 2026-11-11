import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, mensajeDeError } from '../../../core/api/client'
import Can from '../../../shared/components/Can'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import CambiarSerieModal from './CambiarSerieModal'
import ReembolsoModal from './ReembolsoModal'
import {
  AVISOS_ATENCION,
  ayudaSeguimiento,
  ESTADOS_PEDIDO,
  fechaHora,
  MEDIOS_PAGO,
  MODALIDADES_PEDIDO,
  soles,
  textoAccion,
  TIPOS_COMPROBANTE,
} from '../pedidos'

const Pildora = ({ estado }) => {
  const e = ESTADOS_PEDIDO[estado] ?? { texto: estado, tono: 'gris' }
  return (
    <span className="pildora" data-tono={e.tono}>
      {e.texto}
    </span>
  )
}

const Dato = ({ etiqueta, children }) =>
  children ? (
    <div className="pedido-dato">
      <dt>{etiqueta}</dt>
      <dd>{children}</dd>
    </div>
  ) : null

/** Detalle de un pedido con todo lo que el negocio necesita para atenderlo. */
export default function PedidoDetalle({ numero, onCerrar, claveLista }) {
  const clave = ['tienda', 'pedido', numero]
  const consulta = useQuery({
    queryKey: clave,
    queryFn: ({ signal }) => api.get(`/tienda/admin/pedidos/${numero}/`, { signal }).then((r) => r.data),
    refetchOnWindowFocus: false,
  })
  const p = consulta.data

  const [seguimiento, setSeguimiento] = useState('')
  const [nota, setNota] = useState('')
  const [textoNota, setTextoNota] = useState('')
  const [confirmando, setConfirmando] = useState(null) // estado al que se va a pasar
  const [cambiandoSerie, setCambiandoSerie] = useState(null) // línea cuya serie se cambia
  const [reembolsando, setReembolsando] = useState(false)
  const [error, setError] = useState('')

  const invalidar = [clave, claveLista, ['tienda', 'pedidos-resumen']]
  const cambiar = useMutacion({
    mutationFn: ({ estado }) =>
      api.post(`/tienda/admin/pedidos/${numero}/estado/`, { estado, nota, seguimiento }).then((r) => r.data),
    invalidar,
    exito: 'Pedido actualizado.',
    avisarError: false,
    alExito: () => {
      setSeguimiento('')
      setNota('')
      setConfirmando(null)
      setError('')
    },
  })
  const anotar = useMutacion({
    mutationFn: () => api.post(`/tienda/admin/pedidos/${numero}/nota/`, { texto: textoNota }).then((r) => r.data),
    invalidar,
    exito: 'Nota guardada.',
    avisarError: false,
    alExito: () => {
      setTextoNota('')
      setError('')
    },
  })
  const reintentar = useMutacion({
    mutationFn: () => api.post(`/tienda/admin/pedidos/${numero}/reintentar-comprobante/`, {}).then((r) => r.data),
    invalidar,
    exito: (d) => (d.estado === 'PAGADO' ? 'Comprobante emitido.' : 'Sigue pendiente: revisa el motivo.'),
    avisarError: false,
    alExito: () => setError(''),
  })

  const reintentarReembolso = useMutacion({
    mutationFn: () => api.post(`/tienda/admin/pedidos/${numero}/reembolso/reintentar/`, {}).then((r) => r.data),
    invalidar,
    exito: (d) => (d.estado === 'REEMBOLSO_PENDIENTE' ? 'Culqi todavía no confirma: revisa el motivo.' : 'Culqi devolvió el dinero.'),
    avisarError: false,
    alExito: () => setError(''),
  })

  const alError = { onError: (e) => setError(mensajeDeError(e)) }
  const siguientes = p?.acciones?.siguientes ?? []
  const avisoAtencion = p ? AVISOS_ATENCION[p.estado] : null
  const pasaA = confirmando ?? ''

  return (
    <Modal titulo={`Pedido ${numero}`} subtitulo={p ? `${fechaHora(p.creado_en)} · ${MODALIDADES_PEDIDO[p.modalidad]}` : 'Cargando…'} onCerrar={onCerrar} ancho={920}>
      {consulta.isLoading && <p aria-busy="true">Cargando…</p>}
      {consulta.isError && (
        <div role="alert" className="estado-error">
          <p>{mensajeDeError(consulta.error)}</p>
          <button type="button" onClick={() => consulta.refetch()}>
            Reintentar
          </button>
        </div>
      )}
      {p && (
        <div className="pedido-detalle">
          <div className="pedido-estado-fila">
            <Pildora estado={p.estado} />
            <strong>{soles(p.importes.total)}</strong>
            {p.seguimiento && <span className="sub-texto">Seguimiento: {p.seguimiento}</span>}
          </div>

          {avisoAtencion && (
            <div className="pedido-atencion" role="alert">
              <strong>{avisoAtencion.titulo}</strong>
              <p>{avisoAtencion.texto}</p>
              {p.motivo_atencion && (
                <p>
                  <b>Motivo:</b> {p.motivo_atencion}
                </p>
              )}
              {p.estado === 'REEMBOLSO_PENDIENTE' && p.reembolsos?.at(-1)?.mensaje && (
                <p>
                  <b>Lo último que dijo Culqi:</b> {p.reembolsos.at(-1).mensaje}
                </p>
              )}
            </div>
          )}

          {error && (
            <p role="alert" className="campo-error">
              {error}
            </p>
          )}

          <Can permiso="TIENDA.PEDIDOS.GESTIONAR" organizacion>
            {(siguientes.length > 0 || p.acciones.reintentar_comprobante) && (
              <section className="pedido-acciones" aria-label="Atender el pedido">
                {siguientes.length > 0 && (
                  <div className="pedido-campos">
                    {siguientes.some((s) => s.estado === 'ENVIADO' || s.estado === 'LISTO_PARA_RECOJO') && (
                      <label>
                        Seguimiento (opcional)
                        <input value={seguimiento} maxLength={200} onChange={(e) => setSeguimiento(e.target.value)} placeholder="Guía, código o aviso para el cliente" />
                        <span className="sub-texto">{ayudaSeguimiento(siguientes[0].estado)}</span>
                      </label>
                    )}
                    <label>
                      Nota (opcional)
                      <input value={nota} maxLength={500} onChange={(e) => setNota(e.target.value)} placeholder="Queda en el historial" />
                    </label>
                  </div>
                )}
                <div className="pedido-botones">
                  {siguientes.map((s) =>
                    s.estado === 'CANCELADO' ? (
                      <button key={s.estado} type="button" className="peligro" onClick={() => setConfirmando(s.estado)}>
                        {textoAccion(s.estado)}
                      </button>
                    ) : (
                      <button key={s.estado} type="button" className="primario" disabled={cambiar.isPending} onClick={() => cambiar.mutate({ estado: s.estado }, alError)}>
                        {cambiar.isPending ? 'Guardando…' : textoAccion(s.estado)}
                      </button>
                    ),
                  )}
                  {p.acciones.reintentar_comprobante && (
                    <button type="button" className="primario" disabled={reintentar.isPending} onClick={() => reintentar.mutate(undefined, alError)}>
                      {reintentar.isPending ? 'Reintentando…' : 'Reintentar comprobante'}
                    </button>
                  )}
                </div>
                {siguientes.some((s) => p.acciones.avisa_al_cliente.includes(s.estado)) && (
                  <p className="sub-texto">Al marcarlo, el cliente recibe un correo con el aviso.</p>
                )}
              </section>
            )}
          </Can>

          <Can permiso="TIENDA.PEDIDOS.REEMBOLSAR" organizacion>
            {(p.acciones.reembolsar || p.acciones.reintentar_reembolso) && (
              <section className="pedido-acciones pedido-reembolso" aria-label="Reembolso">
                <div className="pedido-botones">
                  {p.acciones.reembolsar && (
                    <button type="button" className="peligro" onClick={() => setReembolsando(true)}>
                      Reembolsar…
                    </button>
                  )}
                  {p.acciones.reintentar_reembolso && (
                    <button type="button" className="primario" disabled={reintentarReembolso.isPending} onClick={() => reintentarReembolso.mutate(undefined, alError)}>
                      {reintentarReembolso.isPending ? 'Reintentando…' : 'Reintentar reembolso'}
                    </button>
                  )}
                </div>
                <p className="sub-texto">Anula o devuelve lo que corresponda y devuelve el dinero al cliente por Culqi. Antes de confirmar verás exactamente qué pasará.</p>
              </section>
            )}
          </Can>

          <div className="pedido-columnas">
            <section aria-label="Cliente y comprobante">
              <h3>Cliente</h3>
              <dl className="pedido-datos">
                <Dato etiqueta="Nombre">{p.cliente.nombre}</Dato>
                <Dato etiqueta="Correo">
                  {p.cliente.correo} {!p.cliente.correo_verificado && <span className="sub-texto">(sin confirmar)</span>}
                </Dato>
                <Dato etiqueta="Celular">{p.cliente.celular}</Dato>
              </dl>
              <h3>Comprobante</h3>
              <dl className="pedido-datos">
                <Dato etiqueta="Tipo">{TIPOS_COMPROBANTE[p.comprobante.tipo] ?? p.comprobante.tipo}</Dato>
                <Dato etiqueta="Nombre">{p.comprobante.nombre}</Dato>
                <Dato etiqueta="Documento">{p.comprobante.documento_numero && `${p.comprobante.documento_tipo} ${p.comprobante.documento_numero}`}</Dato>
                <Dato etiqueta="Dirección fiscal">{p.comprobante.direccion_fiscal}</Dato>
              </dl>
              {p.comprobantes.length > 0 && (
                <ul className="pedido-lista-simple">
                  {p.comprobantes.map((c) => (
                    <li key={c.id}>
                      {c.numero} · {c.empresa} · {soles(c.total)}
                    </li>
                  ))}
                  {p.venta_id && (
                    <li>
                      <Link to={`/ventas/historial/${p.venta_id}`}>Ver la venta en el historial</Link>
                    </li>
                  )}
                </ul>
              )}
            </section>

            <section aria-label="Entrega">
              <h3>{p.modalidad === 'RECOJO' ? 'Recojo en tienda' : 'Envío a domicilio'}</h3>
              <dl className="pedido-datos">
                {p.modalidad === 'RECOJO' ? (
                  <Dato etiqueta="Tienda">{p.entrega.punto}</Dato>
                ) : (
                  <>
                    <Dato etiqueta="Recibe">{p.entrega.receptor}</Dato>
                    <Dato etiqueta="Celular">{p.entrega.celular}</Dato>
                    <Dato etiqueta="Dirección">{p.entrega.direccion}</Dato>
                    <Dato etiqueta="Lugar">{p.entrega.ubicacion}</Dato>
                    <Dato etiqueta="Referencia">{p.entrega.referencia}</Dato>
                    <Dato etiqueta="Zona">{p.entrega.zona}</Dato>
                    <Dato etiqueta="Plazo">{p.entrega.plazo}</Dato>
                  </>
                )}
              </dl>
              {p.entrega.paga_en_destino && <p className="pedido-nota-destino">El cliente paga el flete a la agencia al recibir: no está incluido en el total.</p>}
            </section>
          </div>

          <section aria-label="Productos">
            <h3>Productos</h3>
            <div className="marco-tabla">
              <table className="tabla-datos">
                <thead>
                  <tr>
                    <th>Producto</th>
                    <th>Surte</th>
                    <th className="num">Cant.</th>
                    <th className="num">P. unit.</th>
                    <th className="num">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {p.lineas.map((l, i) => (
                    <tr key={`${l.descripcion}-${i}`}>
                      <td className="col-texto">
                        {l.es_envio ? `${l.descripcion} (envío)` : l.descripcion}
                        {l.series_panel && (
                          <div className="pedido-series">
                            <span className="sub-texto">Serie en el comprobante: {l.series_panel.comprobante.join(', ')}</span>
                            {l.series_panel.cambiada && (
                              <span className="sub-texto">
                                <strong>Serie entregada: {l.series_panel.entregadas.join(', ')}</strong> (cambiada)
                              </span>
                            )}
                            {p.acciones.cambiar_serie && (
                              <Can permiso="TIENDA.PEDIDOS.GESTIONAR" organizacion>
                                <button type="button" className="enlace-boton" onClick={() => setCambiandoSerie(l)}>
                                  Cambiar serie
                                </button>
                              </Can>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="celda-suave">{l.es_envio ? '' : `${l.empresa}${l.almacen ? ` · ${l.almacen}` : ''}`}</td>
                      <td className="num">{l.cantidad}</td>
                      <td className="num">{soles(l.precio_unitario)}</td>
                      <td className="num">{soles(l.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <dl className="pedido-totales">
              <div>
                <dt>Productos</dt>
                <dd>{soles(p.importes.subtotal_productos)}</dd>
              </div>
              {Number(p.importes.costo_envio) > 0 && (
                <div>
                  <dt>Envío</dt>
                  <dd>{soles(p.importes.costo_envio)}</dd>
                </div>
              )}
              <div>
                <dt>IGV incluido</dt>
                <dd>{soles(p.importes.igv)}</dd>
              </div>
              <div className="pedido-total-final">
                <dt>Total</dt>
                <dd>{soles(p.importes.total)}</dd>
              </div>
            </dl>
            {p.importes.igv_exonerado && <p className="sub-texto">IGV exonerado: {p.importes.motivo_igv}</p>}
          </section>

          <div className="pedido-columnas">
            <section aria-label="Pago">
              <h3>Pago</h3>
              <dl className="pedido-datos">
                <Dato etiqueta="Medio">{MEDIOS_PAGO[p.pago.medio] ?? p.pago.medio}</Dato>
                <Dato etiqueta="Pagado el">{p.pago.pagado_en && fechaHora(p.pago.pagado_en)}</Dato>
                <Dato etiqueta="Cargo en Culqi">{p.pago.cargo}</Dato>
                <Dato etiqueta="Reintentos de comprobante">{p.pago.reintentos_comprobante > 0 && p.pago.reintentos_comprobante}</Dato>
              </dl>
              {p.intentos.length > 0 && (
                <ul className="pedido-lista-simple" aria-label="Intentos de pago">
                  {p.intentos.map((i, n) => (
                    <li key={`${i.creado_en}-${n}`}>
                      {fechaHora(i.creado_en)} · {i.estado_texto} · {soles(i.monto)}
                      {i.mensaje && <span className="sub-texto"> — {i.mensaje}</span>}
                    </li>
                  ))}
                </ul>
              )}
              {p.reembolsos?.length > 0 && (
                <>
                  <h3>Reembolsos</h3>
                  <ul className="pedido-lista-simple" aria-label="Reembolsos">
                    {p.reembolsos.map((r) => (
                      <li key={r.id}>
                        {fechaHora(r.aprobado_en ?? r.creado_en)} · {soles(r.monto)} · {r.tipo_texto} · <b>{r.estado_texto}</b>
                        <span className="sub-texto">
                          {' '}
                          — {r.motivo_tipo_texto}: {r.motivo} ({r.usuario})
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {p.deudas_entre_empresas.length > 0 && (
                <ul className="pedido-lista-simple" aria-label="Deuda entre empresas">
                  {p.deudas_entre_empresas.map((d, n) => (
                    <li key={n}>
                      {d.deudora} le debe {soles(d.monto)} a {d.acreedora} · {d.estado_texto ?? (d.liquidada ? 'Liquidada' : 'Por liquidar')}{d.liquidacion_numero ? ` (liquidación N° ${String(d.liquidacion_numero).padStart(6, '0')})` : ''}
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section aria-label="Historial">
              <h3>Historial</h3>
              {p.historial.length === 0 ? (
                <p className="sub-texto">Todavía no hay cambios ni notas.</p>
              ) : (
                <ol className="pedido-historial">
                  {p.historial.map((h, n) => (
                    <li key={`${h.creado_en}-${n}`}>
                      <span className="sub-texto">
                        {fechaHora(h.creado_en)} · {h.usuario}
                      </span>
                      {h.tipo === 'ESTADO' ? (
                        <span>
                          Pasó a <b>{ESTADOS_PEDIDO[h.estado]?.texto ?? h.estado}</b>
                          {h.texto && <i> — {h.texto}</i>}
                        </span>
                      ) : (
                        <span>
                          Nota: <i>{h.texto}</i>
                        </span>
                      )}
                    </li>
                  ))}
                </ol>
              )}
              <Can permiso="TIENDA.PEDIDOS.GESTIONAR" organizacion>
                <form
                  className="pedido-nota-form"
                  onSubmit={(e) => {
                    e.preventDefault()
                    if (textoNota.trim()) anotar.mutate(undefined, alError)
                  }}
                >
                  <label>
                    Agregar nota interna
                    <input value={textoNota} maxLength={500} onChange={(e) => setTextoNota(e.target.value)} placeholder="Solo la ve tu equipo" />
                  </label>
                  <button type="submit" disabled={!textoNota.trim() || anotar.isPending}>
                    {anotar.isPending ? 'Guardando…' : 'Guardar nota'}
                  </button>
                </form>
              </Can>
            </section>
          </div>
        </div>
      )}

      {reembolsando && <ReembolsoModal numero={numero} lineas={p?.lineas ?? []} invalidar={invalidar} onCerrar={() => setReembolsando(false)} />}

      {cambiandoSerie && (
        <CambiarSerieModal numero={numero} linea={cambiandoSerie} invalidar={invalidar} onCerrar={() => setCambiandoSerie(null)} />
      )}

      {confirmando && (
        <ConfirmarModal
          titulo="¿Cancelar este pedido?"
          mensaje="El pedido aún no se pagó. Se libera el stock apartado y el cliente ya no podrá pagarlo."
          textoConfirmar="Sí, cancelar pedido"
          enviando={cambiar.isPending}
          onConfirmar={() => cambiar.mutate({ estado: pasaA }, alError)}
          onCerrar={() => setConfirmando(null)}
        />
      )}
    </Modal>
  )
}
