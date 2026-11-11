import { useQuery } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import BotonVolver from '../../../shared/components/BotonVolver'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { hoyIso } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import CarritoVenta from '../components/CarritoVenta'
import CatalogoVenta from '../components/CatalogoVenta'
import ClienteVenta from '../components/ClienteVenta'
import { useConfiguracionVenta } from '../hooks/useConfiguracionVenta'
import { agregarAlCarrito, borradorInicial, cuerpoProforma, empresasCandidatas, FORMAS_PAGO, sumarDias, validarProforma } from '../ventas'
import '../../almacen/inventario.css'
import '../../compras/compras.css'
import '../consulta.css'
import '../ventas.css'

/** El formulario de una proforma: a quién se cotiza, qué se cotiza, cuándo se entrega y las condiciones. */
function Formulario({ config, empresaId, sucursal }) {
  const navegar = useNavigate()
  const permisos = config.permisos
  const hoy = hoyIso()
  const candidatas = useMemo(() => empresasCandidatas(config.empresas, empresaId, permisos.otra_empresa), [config.empresas, empresaId, permisos.otra_empresa])
  const [b, setB] = useState(() => borradorInicial(config, hoy))
  const [datos, setDatos] = useState({ nombre: '', documento: '', contacto: '', direccion: '', entrega: '', validez: '7', atencion: '', lugar: '', condiciones: '' })
  const [aviso, setAviso] = useState('')
  const [serieElegida, setSerieElegida] = useState('')
  const [intento, setIntento] = useState(false)
  const [general, setGeneral] = useState('')
  const poner = (campo, valor) => setB((previo) => ({ ...previo, [campo]: valor }))
  const ponerDato = (campo) => (e) => setDatos((previo) => ({ ...previo, [campo]: e.target.value }))

  // --- Cálculo del servidor (IGV y totales), sin guardar nada ---
  const cuerpoPrevio = useMemo(() => {
    const e = cuerpoProforma(b, { empresa: empresaId, sucursal }, { clienteNombre: '', clienteDocumento: '', contacto: '', validez: '7', condiciones: '' })
    return { ...e, tipo_comprobante: b.tipo, forma_pago: b.formaPago, lista: b.formaPago === 'CONTADO' && b.lista ? b.lista : undefined }
  }, [b, empresaId, sucursal])
  const enviadas = useMemo(() => b.lineas.filter((l) => Number(l.cantidad) > 0), [b.lineas])
  const demorado = useDebounce(cuerpoPrevio, 350)
  const hayLineas = cuerpoPrevio.lineas.length > 0
  const previo = useQuery({
    queryKey: ['ventas', 'previsualizar', demorado],
    queryFn: ({ signal }) => api.post('/ventas/previsualizar/', demorado, { signal }).then((r) => r.data),
    enabled: demorado.lineas.length > 0,
    retry: false,
    staleTime: 0,
    placeholderData: (anterior) => anterior,
  })
  const calculo = hayLineas ? previo.data : undefined
  const calculando = hayLineas && (JSON.stringify(demorado) !== JSON.stringify(cuerpoPrevio) || previo.isFetching)
  const errorDeCalculo = hayLineas && previo.isError ? mensajeDeError(previo.error) : ''
  const porLinea = useMemo(() => {
    const mapa = new Map()
    if (!calculo || calculando) return mapa
    for (const c of calculo.comprobantes) for (const l of c.lineas) if (enviadas[l.indice]) mapa.set(enviadas[l.indice].id, l)
    return mapa
  }, [calculo, calculando, enviadas])
  const suma = (campo) => (calculo?.comprobantes ?? []).reduce((s, c) => s + Number(c[campo] ?? 0), 0)

  const agregar = useCallback(
    (ficha) => {
      const r = agregarAlCarrito(b.lineas, ficha, candidatas, empresaId)
      setAviso(r.aviso)
      if (r.lineas !== b.lineas) setB((previo) => ({ ...previo, lineas: r.lineas }))
    },
    [b.lineas, candidatas, empresaId],
  )
  const cambiarLinea = (nueva) => setB((previo) => ({ ...previo, lineas: previo.lineas.map((l) => (l.id === nueva.id ? nueva : l)) }))
  const quitarLinea = (id) => setB((previo) => ({ ...previo, lineas: previo.lineas.filter((l) => l.id !== id) }))
  const cambiarForma = (formaPago) => setB((previo) => ({ ...previo, formaPago, lineas: previo.lineas.map((l) => ({ ...l, precio: '' })) }))
  const cambiarLista = (id) => setB((previo) => ({ ...previo, lista: Number(id), lineas: previo.lineas.map((l) => ({ ...l, precio: '' })) }))
  const cambiarMoneda = (moneda) => setB((previo) => ({ ...previo, moneda, tipoCambioManual: false, tipoCambio: config.tipo_cambio?.compra ?? '', lineas: previo.lineas.map((l) => ({ ...l, precio: '' })) }))
  const enCarrito = useMemo(() => new Set(b.lineas.map((l) => l.ficha.id)), [b.lineas])
  const credito = b.formaPago === 'CREDITO'
  const listaCredito = config.listas.find((l) => l.id === config.credito.lista)
  const lista = credito ? listaCredito : config.listas.find((l) => l.id === b.lista)
  // La entrega sigue a la validez (fecha de la proforma + días) mientras no se escriba otra fecha.
  const dias = Number(datos.validez)
  const entrega = datos.entrega || (Number.isInteger(dias) && dias > 0 ? sumarDias(hoy, dias) : '')
  // Las series de proformas de la empresa que sirven a esta tienda (las de su sucursal y las generales).
  const series = (config.empresas.find((e) => e.id === empresaId)?.series_proforma ?? []).filter((x) => x.sucursal === null || x.sucursal === sucursal)
  const serie = series.find((x) => String(x.id) === serieElegida) ?? series[0]

  const guardar = useMutacion({
    mutationFn: (cuerpo) => api.post('/ventas/proformas/', cuerpo, { timeout: 30_000 }).then((r) => r.data),
    invalidar: [['ventas']],
    exito: (p) => `Proforma ${p.numero_completo} guardada.`,
    alExito: (p) => navegar(`/ventas/proformas/${p.id}`),
    avisarError: false,
  })
  const errores = validarProforma({ lineas: b.lineas, cliente: b.cliente, clienteNombre: datos.nombre, validez: datos.validez })
  if (entrega && entrega < hoy) errores.push('La fecha de entrega no puede ser anterior a hoy.')
  if (!serie) errores.push('Falta la serie de proformas: créala en Mantenimiento → Series de comprobantes.')

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending) return
    setIntento(true)
    setGeneral('')
    if (errores.length > 0 || calculando || errorDeCalculo) return
    const cuerpo = cuerpoProforma(b, { empresa: empresaId, sucursal }, { clienteNombre: datos.nombre, clienteDocumento: datos.documento, contacto: datos.contacto, validez: datos.validez, condiciones: datos.condiciones })
    cuerpo.serie = serie.id
    if (datos.direccion.trim()) cuerpo.cliente_direccion = datos.direccion.trim()
    if (entrega) cuerpo.fecha_entrega = entrega
    if (credito) cuerpo.forma_pago = 'CREDITO'
    if (datos.atencion.trim()) cuerpo.atencion = datos.atencion.trim()
    if (datos.lugar.trim()) cuerpo.lugar_entrega = datos.lugar.trim()
    guardar.mutate(cuerpo, { onError: (e) => setGeneral(Object.keys(erroresDeCampo(e)).length ? 'Revisa los datos de la proforma.' : mensajeDeError(e)) })
  }
  const enviando = guardar.isPending

  return (
    <form onSubmit={enviar} noValidate className="pos-layout">
      <div className="compra-layout">
        <div className="compra-principal">
          <PanelTarjeta icono="user" titulo="Cliente y fechas" descripcion="Para quién es la cotización, cuándo se hace y hasta cuándo vale.">
            <div className="pos-bloques">
              <ClienteVenta cliente={b.cliente} onElegir={(c) => poner('cliente', c)} disabled={enviando} obligatorio={false} />
              {b.cliente ? (
                <p className="celda-suave" role="status">
                  Se usan los datos registrados del cliente
                  {[b.cliente.direccion, b.cliente.telefono, b.cliente.correo].filter(Boolean).length > 0 ? `: ${[b.cliente.direccion, b.cliente.telefono, b.cliente.correo].filter(Boolean).join(' · ')}` : ' (no tiene dirección ni teléfono cargados)'}.
                </p>
              ) : (
                <>
                  <div className="fila-campos">
                    <Campo etiqueta="¿Para quién es?" requerido ayuda="Elige un cliente arriba, o escribe el nombre de quien pidió la cotización.">
                      {(p) => <input {...p} maxLength={250} value={datos.nombre} disabled={enviando} onChange={ponerDato('nombre')} />}
                    </Campo>
                    <Campo etiqueta="DNI o RUC" ayuda="Opcional.">
                      {(p) => <input {...p} maxLength={20} value={datos.documento} disabled={enviando} onChange={ponerDato('documento')} />}
                    </Campo>
                  </div>
                  <div className="fila-campos">
                    <Campo etiqueta="Dirección">
                      {(p) => <input {...p} maxLength={250} placeholder="Opcional" value={datos.direccion} disabled={enviando} onChange={ponerDato('direccion')} />}
                    </Campo>
                    <Campo etiqueta="Teléfono o correo">
                      {(p) => <input {...p} maxLength={120} placeholder="Opcional" value={datos.contacto} disabled={enviando} onChange={ponerDato('contacto')} />}
                    </Campo>
                  </div>
                </>
              )}
              <div className="fila-campos">
                {series.length > 1 ? (
                  <Campo etiqueta="Serie · próximo N°" tipo="select" requerido>
                    {(p) => (
                      <select {...p} value={serie.id} disabled={enviando} onChange={(e) => setSerieElegida(e.target.value)}>
                        {series.map((x) => (
                          <option key={x.id} value={x.id}>
                            {x.proximo}
                            {x.nombre ? ` · ${x.nombre}` : ''}
                          </option>
                        ))}
                      </select>
                    )}
                  </Campo>
                ) : (
                  <Campo etiqueta="Serie · próximo N°">{(p) => <input {...p} value={serie?.proximo ?? 'Sin serie'} readOnly disabled />}</Campo>
                )}
                <Campo etiqueta="Fecha de la proforma" icono="calendario">
                  {(p) => <input {...p} type="date" value={hoy} readOnly disabled />}
                </Campo>
                <Campo etiqueta="Fecha de entrega" icono="calendario" ayuda="Sigue a los días de validez; cámbiala si es otra.">
                  {(p) => <input {...p} type="date" min={hoy} value={entrega} disabled={enviando} onChange={ponerDato('entrega')} />}
                </Campo>
                <Campo etiqueta="Válida por (días)" requerido>
                  {(p) => <input {...p} inputMode="numeric" value={datos.validez} disabled={enviando} onChange={(e) => setDatos((previo) => ({ ...previo, validez: e.target.value.replace(/\D/g, '') }))} />}
                </Campo>
                <Campo etiqueta="Vendedor" tipo={permisos.elegir_vendedor && config.vendedores.length > 0 ? 'select' : undefined}>
                  {(p) =>
                    permisos.elegir_vendedor && config.vendedores.length > 0 ? (
                      <select {...p} value={b.vendedor} disabled={enviando} onChange={(e) => poner('vendedor', e.target.value)}>
                        {config.vendedores.map((v) => (
                          <option key={v.id} value={v.id}>
                            {v.nombre}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input {...p} value={config.vendedor.nombre} readOnly />
                    )
                  }
                </Campo>
              </div>
              {permisos.credito && (
                <div className="segmentos" role="radiogroup" aria-label="Forma de pago de la cotización">
                  {Object.entries(FORMAS_PAGO).map(([valor, texto]) => (
                    <button key={valor} type="button" role="radio" aria-checked={b.formaPago === valor} className={b.formaPago === valor ? 'activo' : undefined} disabled={enviando} onClick={() => cambiarForma(valor)}>
                      {texto}
                    </button>
                  ))}
                </div>
              )}
              <div className="fila-campos">
                <Campo etiqueta="Lista de precios" tipo="select" ayuda={credito ? 'A crédito se usa el precio de crédito.' : undefined}>
                  {(p) => (
                    <select {...p} value={credito ? (config.credito.lista ?? '') : (b.lista ?? '')} disabled={enviando || credito} onChange={(e) => cambiarLista(e.target.value)}>
                      {credito && listaCredito && <option value={listaCredito.id}>{listaCredito.nombre}</option>}
                      {!credito &&
                        config.listas
                        .filter((l) => l.permitida)
                        .map((l) => (
                          <option key={l.id} value={l.id}>
                            {l.nombre}
                          </option>
                        ))}
                    </select>
                  )}
                </Campo>
                <Campo etiqueta="Moneda" tipo="select">
                  {(p) => (
                    <select {...p} value={b.moneda} disabled={enviando} onChange={(e) => cambiarMoneda(e.target.value)}>
                      <option value="PEN">Soles (S/)</option>
                      <option value="USD">Dólares (US$)</option>
                    </select>
                  )}
                </Campo>
                {b.moneda === 'USD' && (
                  <Campo etiqueta="Tipo de cambio">
                    {(p) => <input {...p} inputMode="decimal" value={b.tipoCambio} readOnly={!permisos.cambiar_tipo_cambio} disabled={enviando} onChange={(e) => setB((previo) => ({ ...previo, tipoCambio: e.target.value.replace(',', '.'), tipoCambioManual: true }))} />}
                  </Campo>
                )}
              </div>
              {b.moneda === 'USD' && !config.tipo_cambio && <p className="compra-aviso">No hay tipo de cambio del día. Pide que lo registren en Mantenimiento.</p>}
            </div>
          </PanelTarjeta>

          <PanelTarjeta icono="package" titulo={`Productos${b.lineas.length ? ` (${b.lineas.length})` : ''}`} descripcion={lista ? `Escribe o escanea para agregar. Precios de la lista «${lista.nombre}», sin IGV.` : 'Escribe o escanea para agregar.'}>
            <div className="pos-bloques">
              <CatalogoVenta empresaId={empresaId} categorias={config.categorias} lista={credito ? config.credito.lista : b.lista} empresas={candidatas} enCarrito={enCarrito} onAgregar={agregar} onAviso={setAviso} />
              {aviso && (
                <p className="compra-aviso" role="status">
                  {aviso}
                </p>
              )}
              <CarritoVenta lineas={b.lineas} calculos={porLinea} empresas={config.empresas} candidatas={candidatas} afectaciones={config.afectaciones ?? []} moneda={b.moneda} disabled={enviando} onCambiar={cambiarLinea} onQuitar={quitarLinea} />
              {b.lineas.length > 0 && (
                <button type="button" className="pos-chip peligro" disabled={enviando} onClick={() => poner('lineas', [])}>
                  <Icono nombre="papelera" tam={16} /> Vaciar la lista
                </button>
              )}
            </div>
          </PanelTarjeta>

          <PanelTarjeta icono="documento" titulo="Entrega y notas" descripcion="A quién se dirige, dónde se entrega y las condiciones de la cotización.">
            <div className="pos-bloques">
              <div className="fila-campos">
                <Campo etiqueta="Con atención a">
                  {(p) => <input {...p} maxLength={120} placeholder="Opcional" value={datos.atencion} disabled={enviando} onChange={ponerDato('atencion')} />}
                </Campo>
                <Campo etiqueta="Lugar de entrega">
                  {(p) => <input {...p} maxLength={250} placeholder="Opcional" value={datos.lugar} disabled={enviando} onChange={ponerDato('lugar')} />}
                </Campo>
              </div>
              <Campo etiqueta="Nota de la proforma" contador={{ actual: datos.condiciones.length, max: 500 }} ayuda="Opcional: garantía, forma de pago, tiempo de entrega…">
                {(p) => <textarea {...p} rows={3} maxLength={500} value={datos.condiciones} disabled={enviando} onChange={ponerDato('condiciones')} />}
              </Campo>
            </div>
          </PanelTarjeta>
        </div>

        <aside className="compra-resumen" aria-label="Resumen de la proforma">
          <h3>Resumen</h3>
          {!serie && (
            <p role="alert" className="compra-aviso">
              Esta empresa no tiene una serie de proformas. Créala en Mantenimiento → Series de comprobantes (tipo «Proforma», por ejemplo P001) para poder guardar.
            </p>
          )}
          <p className="celda-suave">
            {b.lineas.length} {b.lineas.length === 1 ? 'producto' : 'productos'}
          </p>
          {errorDeCalculo && (
            <p role="alert" className="compra-aviso">
              {errorDeCalculo}
            </p>
          )}
          <dl className="compra-totales" aria-busy={calculando}>
            <div>
              <dt>Subtotal</dt>
              <dd>{calculando || !calculo ? '—' : dinero(suma('op_gravada') + suma('op_exonerada') + suma('op_inafecta'), b.moneda)}</dd>
            </div>
            <div>
              <dt>IGV</dt>
              <dd>{calculando || !calculo ? '—' : dinero(suma('igv'), b.moneda)}</dd>
            </div>
            <div className="compra-total">
              <dt>Total</dt>
              <dd aria-live="polite">{calculando ? 'Calculando…' : calculo ? dinero(suma('total'), b.moneda) : dinero(0, b.moneda)}</dd>
            </div>
          </dl>
          {calculo?.avisos?.some((m) => !/crédito/i.test(m)) && (
            <ul className="pos-avisos" role="status">
              {calculo.avisos.filter((m) => !/crédito/i.test(m)).map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          )}
          {intento && errores.length > 0 && (
            <div className="compra-faltan">
              <strong>Para guardar falta:</strong>
              <ul>
                {[...new Set(errores)].map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            </div>
          )}
          {general && (
            <p role="alert" className="campo-error">
              {general}
            </p>
          )}
          <button type="submit" className="primario pos-generar" disabled={enviando || calculando || b.lineas.length === 0 || !serie}>
            <Icono nombre="documento" tam={20} />
            {enviando ? 'Guardando…' : 'Guardar proforma'}
          </button>
          <button type="button" className="boton-cabecera" disabled={enviando} onClick={() => navegar('/ventas/proformas')}>
            Cancelar
          </button>
          <small className="celda-suave">Una proforma no mueve stock ni dinero. Cuando el cliente acepta, se convierte en venta y ahí sí se descuenta el stock y se cobra en caja.</small>
        </aside>
      </div>
    </form>
  )
}

/** Nueva proforma: una cotización con su formulario completo. */
export default function NuevaProformaPage() {
  const { empresaActivaId, empresaActiva } = useEmpresas()
  const config = useConfiguracionVenta(empresaActivaId, null)
  return (
    <main className="listado pos-pagina">
      <BotonVolver ruta="/ventas/proformas" texto="Volver a Proformas" />
      <CabeceraListado icono="cotizacion" titulo="Nueva proforma" descripcion={`Cotización de ${empresaActiva?.nombre_comercial || empresaActiva?.razon_social || 'la empresa activa'}. No mueve stock ni dinero hasta que se convierte en venta.`} />
      <EstadoConsulta consulta={config} hayDatos={Boolean(config.data)}>
        {config.data && (config.data.empresas.length === 0 ? <p className="estado-vacio">No tienes empresas habilitadas para vender.</p> : <Formulario key={empresaActivaId} config={config.data} empresaId={empresaActivaId} sucursal={config.sucursal} />)}
      </EstadoConsulta>
    </main>
  )
}
