import { useQuery } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, mensajeDeError } from '../../../core/api/client'
import BotonVolver from '../../../shared/components/BotonVolver'
import Can from '../../../shared/components/Can'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaCorta } from '../../almacen/inventario'
import AccionConNotaModal from '../../caja/components/AccionConNotaModal'
import { pesoLegible, validarVoucher } from '../../caja/caja'
import PagarGastoModal from '../components/PagarGastoModal'
import { dinero, ESTADOS_PAGO } from '../gastos'
import '../../almacen/inventario.css'
import '../../compras/compras.css'
import '../gastos.css'

const RUTA = '/gastos/registro'

function Dato({ titulo, children }) {
  return (
    <div className="gasto-dato">
      <dt>{titulo}</dt>
      <dd>{children}</dd>
    </div>
  )
}

/** Comprobantes del gasto (foto o PDF): se ven y se descargan con la sesión iniciada. */
function Comprobantes({ gasto, puedeSubir }) {
  const entrada = useRef(null)
  const [error, setError] = useState('')
  const vigente = gasto.estado === 'EMITIDO'
  const subir = useMutacion({
    mutationFn: (archivo) => {
      const cuerpo = new FormData()
      cuerpo.append('gasto', gasto.id)
      cuerpo.append('archivo', archivo)
      return api.post('/gastos/adjuntos/', cuerpo, { timeout: 60_000 }).then((r) => r.data)
    },
    invalidar: [['gastos']],
    exito: 'Comprobante guardado.',
    avisarError: false,
  })
  const quitar = useMutacion({
    mutationFn: (id) => api.delete(`/gastos/adjuntos/${id}/`),
    invalidar: [['gastos']],
    exito: 'Comprobante quitado.',
    avisarError: false,
  })
  const elegir = (evento) => {
    const archivo = evento.target.files?.[0]
    evento.target.value = ''
    const malo = validarVoucher(archivo)
    setError(malo)
    if (malo || subir.isPending) return
    subir.mutate(archivo, { onError: (e) => setError(mensajeDeError(e)) })
  }
  const ver = async (adjunto) => {
    setError('')
    try {
      const respuesta = await api.get(`/gastos/adjuntos/${adjunto.id}/archivo/`, { responseType: 'blob' })
      const direccion = URL.createObjectURL(respuesta.data)
      window.open(direccion, '_blank', 'noopener')
      setTimeout(() => URL.revokeObjectURL(direccion), 60_000)
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  return (
    <PanelTarjeta icono="camara" titulo="Foto o PDF del comprobante" descripcion="El respaldo del gasto. Solo se ve con tu sesión iniciada.">
      {gasto.adjuntos.length === 0 ? (
        <p className="estado-vacio">{gasto.con_comprobante ? 'Todavía no guardaste la foto del comprobante.' : 'Un gasto sin comprobante puede llevar una foto del lugar o del ticket, si la hay.'}</p>
      ) : (
        <ul className="voucher-lista">
          {gasto.adjuntos.map((a) => (
            <li key={a.id}>
              <span>{a.tipo_contenido === 'application/pdf' ? 'PDF' : 'Foto'}</span>
              <span className="celda-suave">
                {a.nombre_original || 'Sin nombre'} · {pesoLegible(a.tamano)} · {a.subido_por_nombre}
              </span>
              <button type="button" className="boton-cabecera" onClick={() => ver(a)}>
                <Icono nombre="ojo" tam={17} /> Ver
              </button>
              {puedeSubir && vigente && (
                <button type="button" className="accion-icono peligro-suave" aria-label="Quitar el comprobante" title="Quitar" disabled={quitar.isPending} onClick={() => quitar.mutate(a.id, { onError: (e) => setError(mensajeDeError(e)) })}>
                  <Icono nombre="papelera" tam={18} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {puedeSubir && vigente && gasto.adjuntos.length < 5 && (
        <>
          <input ref={entrada} type="file" accept="image/jpeg,image/png,image/webp,application/pdf" hidden onChange={elegir} />
          <button type="button" className="boton-cabecera" disabled={subir.isPending} onClick={() => entrada.current?.click()}>
            <Icono nombre="camara" tam={18} /> {subir.isPending ? 'Guardando…' : 'Agregar foto o PDF'}
          </button>
        </>
      )}
      {error && (
        <p role="alert" className="campo-error">
          {error}
        </p>
      )}
    </PanelTarjeta>
  )
}

/** Ficha de un gasto: datos, pagos, reparto entre empresas y comprobantes. */
export default function GastoFichaPage() {
  const { id } = useParams()
  const { tiene } = usePermisos()
  const [anulando, setAnulando] = useState(false)
  const [pagando, setPagando] = useState(false)
  const [anulandoPago, setAnulandoPago] = useState(null)
  const consulta = useQuery({
    queryKey: ['gastos', 'ficha', id],
    queryFn: ({ signal }) => api.get(`/gastos/${id}/`, { signal }).then((r) => r.data),
  })
  const g = consulta.data
  const pago = g && ESTADOS_PAGO[g.estado_pago]

  return (
    <main className="listado compra-pagina">
      <BotonVolver ruta={RUTA} texto="Volver a Gastos" />
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(g)}>
        {g && (
          <>
            <CabeceraListado icono="coins" titulo={`Gasto N° ${String(g.numero).padStart(6, '0')}`} descripcion={g.descripcion}>
              <span className="pildora" data-tono={pago.tono}>
                {pago.texto}
              </span>
              {g.estado === 'EMITIDO' && Number(g.saldo) > 0 && (
                <Can permiso="GASTOS.PAGAR">
                  <button type="button" className="primario boton-cabecera" onClick={() => setPagando(true)}>
                    <Icono nombre="wallet" tam={18} /> Pagar
                  </button>
                </Can>
              )}
              {g.estado === 'EMITIDO' && (
                <Can permiso="GASTOS.ANULAR">
                  <button type="button" className="boton-cabecera" onClick={() => setAnulando(true)}>
                    <Icono nombre="apagar" tam={18} /> Anular
                  </button>
                </Can>
              )}
            </CabeceraListado>

            {g.estado === 'ANULADO' && <p className="compra-aviso">Gasto anulado: {g.motivo_anulacion}. El dinero de sus pagos volvió a las cajas.</p>}
            {g.sin_sustento && g.estado === 'EMITIDO' && <p className="compra-aviso">Sin comprobante: no sirve como crédito fiscal ni sale en el registro de compras. Queda marcado «sin sustento».</p>}

            <PanelTarjeta icono="documento" titulo="Datos del gasto">
              <dl className="gasto-cabecera-ficha">
                <Dato titulo="Fecha">{fechaCorta(g.fecha)}</Dato>
                <Dato titulo="Categoría">{g.categoria_nombre}</Dato>
                <Dato titulo="Empresa">{g.empresa_nombre}</Dato>
                {g.sucursal_nombre && <Dato titulo="Tienda">{g.sucursal_nombre}</Dato>}
                {g.con_comprobante ? (
                  <>
                    <Dato titulo="Comprobante">
                      {g.tipo_comprobante_nombre} {g.comprobante}
                    </Dato>
                    <Dato titulo="Proveedor">{g.proveedor_nombre ? `${g.proveedor_nombre} (${g.proveedor_documento})` : '—'}</Dato>
                  </>
                ) : (
                  <Dato titulo="Lo gastó">{g.gastado_por}</Dato>
                )}
                {g.observacion && <Dato titulo="Nota">{g.observacion}</Dato>}
              </dl>
            </PanelTarjeta>

            <PanelTarjeta icono="coins" titulo="Importe">
              <dl className="cxp-tarjetas" aria-label="Importes del gasto">
                {Number(g.base_gravada) > 0 && (
                  <div>
                    <dt>Base gravada</dt>
                    <dd>{dinero(g.base_gravada, g.moneda)}</dd>
                  </div>
                )}
                {Number(g.igv) > 0 && (
                  <div>
                    <dt>IGV</dt>
                    <dd>{dinero(g.igv, g.moneda)}</dd>
                  </div>
                )}
                {Number(g.no_gravado) > 0 && Number(g.base_gravada) > 0 && (
                  <div>
                    <dt>Sin IGV</dt>
                    <dd>{dinero(g.no_gravado, g.moneda)}</dd>
                  </div>
                )}
                <div>
                  <dt>Total</dt>
                  <dd>{dinero(g.total, g.moneda)}</dd>
                  {g.moneda === 'USD' && <small>Tipo de cambio {g.tipo_cambio}</small>}
                </div>
                <div>
                  <dt>Pagado</dt>
                  <dd>{dinero(g.pagado, g.moneda)}</dd>
                </div>
                <div data-tono={g.estado === 'EMITIDO' && Number(g.saldo) > 0 ? 'ambar' : undefined}>
                  <dt>Por pagar</dt>
                  <dd>{dinero(g.saldo, g.moneda)}</dd>
                  {g.fecha_vencimiento && Number(g.saldo) > 0 && <small>Vence {fechaCorta(g.fecha_vencimiento)}</small>}
                </div>
              </dl>
            </PanelTarjeta>

            <PanelTarjeta icono="wallet" titulo="Pagos" descripcion="Con qué método y de qué caja o cuenta salió el dinero.">
              {g.pagos.length === 0 ? (
                <p className="estado-vacio">Todavía no se pagó este gasto.</p>
              ) : (
                <div className="marco-tabla">
                  <table className="tabla-datos">
                    <thead>
                      <tr>
                        <th>Fecha</th>
                        <th>Método</th>
                        <th>Caja o cuenta</th>
                        <th className="num">Monto</th>
                        <th className="centrado">
                          <span className="sr-only">Acciones</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {g.pagos.map((p) => (
                        <tr key={p.id} className={p.anulado ? 'anulado' : undefined}>
                          <td>{fechaCorta(p.fecha)}</td>
                          <td>
                            {p.medio_nombre}
                            {p.referencia && <span className="sub-texto">Operación {p.referencia}</span>}
                          </td>
                          <td>{p.cuenta_nombre}</td>
                          <td className="num">
                            {dinero(p.monto, g.moneda)}
                            {p.tipo_cambio && <span className="sub-texto">Salió {dinero(p.monto_cuenta, p.moneda_cuenta)} (cambio {p.tipo_cambio})</span>}
                            {p.anulado && <span className="sub-texto">Anulado: {p.motivo_anulacion}</span>}
                          </td>
                          <td className="centrado">
                            {!p.anulado && g.estado === 'EMITIDO' && g.forma_pago === 'POR_PAGAR' && tiene('GASTOS.ANULAR') && (
                              <button type="button" className="accion-icono peligro-suave" aria-label="Anular este pago" title="Anular este pago" onClick={() => setAnulandoPago(p)}>
                                <Icono nombre="apagar" tam={19} />
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </PanelTarjeta>

            {g.repartos.length > 0 && (
              <PanelTarjeta icono="building" titulo="Reparto entre empresas" descripcion="El comprobante y el IGV son de la empresa que lo registró; esto es lo que le toca a cada una.">
                <div className="marco-tabla">
                  <table className="tabla-datos">
                    <thead>
                      <tr>
                        <th>Empresa</th>
                        <th className="num">Porcentaje</th>
                        <th className="num">Le toca</th>
                      </tr>
                    </thead>
                    <tbody>
                      {g.repartos.map((r) => (
                        <tr key={r.id}>
                          <td>{r.empresa_nombre}</td>
                          <td className="num">{r.porcentaje}%</td>
                          <td className="num">{dinero(r.monto, g.moneda)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </PanelTarjeta>
            )}

            <Comprobantes gasto={g} puedeSubir={tiene('GASTOS.REGISTRAR')} />
          </>
        )}
      </EstadoConsulta>
      {pagando && g && <PagarGastoModal gasto={g} onCerrar={() => setPagando(false)} />}
      {anulandoPago && (
        <AccionConNotaModal
          url={`/gastos/${id}/pagos/${anulandoPago.id}/anular/`}
          invalidar={[['gastos'], ['caja']]}
          titulo="Anular el pago"
          subtitulo={`${anulandoPago.medio_nombre} · ${dinero(anulandoPago.monto, g.moneda)}`}
          descripcion="El dinero vuelve a la caja de donde salió y el gasto vuelve a deber ese monto."
          campo="motivo"
          etiqueta="Motivo"
          requerido
          placeholder="Ej. Se pagó desde la cuenta equivocada"
          boton="Anular el pago"
          ocupado="Anulando…"
          exito="Pago anulado."
          peligro
          alExito={() => consulta.refetch()}
          onCerrar={() => setAnulandoPago(null)}
        />
      )}
      {anulando && (
        <AccionConNotaModal
          url={`/gastos/${id}/anular/`}
          invalidar={[['gastos'], ['caja']]}
          titulo="Anular el gasto"
          subtitulo={g ? `N° ${String(g.numero).padStart(6, '0')} · ${dinero(g.total, g.moneda)}` : undefined}
          descripcion="Si ya se pagó, el dinero vuelve a las cajas de donde salió. El gasto no se borra: queda anulado con su motivo."
          campo="motivo"
          etiqueta="Motivo"
          requerido
          placeholder="Ej. Se registró dos veces"
          boton="Anular"
          ocupado="Anulando…"
          exito="Gasto anulado."
          peligro
          alExito={() => consulta.refetch()}
          onCerrar={() => setAnulando(false)}
        />
      )}
    </main>
  )
}
