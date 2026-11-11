import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { fechaCorta, hoyIso } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import CarritoVenta from '../components/CarritoVenta'
import CatalogoVenta from '../components/CatalogoVenta'
import ClienteVenta from '../components/ClienteVenta'
import CobroVenta from '../components/CobroVenta'
import VentaHechaModal from '../components/VentaHechaModal'
import VentaInternaVenta from '../components/VentaInternaVenta'
import { useConfiguracionVenta } from '../hooks/useConfiguracionVenta'
import { aDinero, agregarAlCarrito, borradorDeProforma, borradorInicial, cuerpoCarrito, cuerpoVenta, CUOTAS_MAXIMAS, empresasCandidatas, facturadoraEfectiva, FORMAS_PAGO, medioPorDefecto, totalCobrado, validarVenta } from '../ventas'
import '../../almacen/inventario.css'
import '../../compras/compras.css'
import '../consulta.css'
import '../ventas.css'

/** El mostrador: catálogo a la izquierda; a la derecha el carrito, lo que cobra cada empresa y el cobro. */
function Mostrador({ config, empresaId, sucursal, onSucursal, proforma }) {
  const permisos = config.permisos
  const candidatas = useMemo(() => empresasCandidatas(config.empresas, empresaId, permisos.otra_empresa), [config.empresas, empresaId, permisos.otra_empresa])
  const hoy = hoyIso()
  // Con una proforma, el carrito arranca con sus líneas (las que no se pueden cargar se avisan).
  const [inicial] = useState(() => (proforma ? borradorDeProforma(borradorInicial(config, hoy), proforma, { candidatas, mostradorId: empresaId, puedeCredito: permisos.credito }) : { borrador: borradorInicial(config, hoy), avisos: [] }))
  const [b, setB] = useState(inicial.borrador)
  const [aviso, setAviso] = useState(inicial.avisos.join(' '))
  const [intento, setIntento] = useState(false)
  // El error del último intento de cobrar vale solo para lo que se envió: si el carrito o los cobros cambian, ya no se muestra.
  const [fallo, setFallo] = useState({ texto: '', huella: '' })
  const [hecha, setHecha] = useState(null)
  const poner = (campo, valor) => setB((previo) => ({ ...previo, [campo]: valor }))

  // --- Cálculo del servidor (IGV y totales de cada empresa), sin guardar nada ---
  const credito = b.formaPago === 'CREDITO'
  const empresasDelCarrito = useMemo(() => [...new Set(b.lineas.map((l) => l.empresa))], [b.lineas])
  // Venta interna: con un solo comprobante emite únicamente la empresa elegida y a ella entra todo el cobro.
  const facturarPor = facturadoraEfectiva(b.facturarPor, empresasDelCarrito, permisos.venta_interna)
  const emisoras = useMemo(() => (facturarPor ? [facturarPor] : empresasDelCarrito), [facturarPor, empresasDelCarrito])
  // Si una empresa tiene varias series del tipo elegido, se usa la elegida (o la primera) y se avisa al servidor.
  const seriesDe = useCallback((id) => (config.empresas.find((e) => e.id === id)?.series ?? []).filter((x) => x.tipo === b.tipo), [config.empresas, b.tipo])
  const empresasConSeries = useMemo(() => (emisoras.length ? emisoras : [empresaId]).filter((id) => seriesDe(id).length > 1), [emisoras, empresaId, seriesDe])
  const empresasVisibles = useMemo(() => (emisoras.length ? emisoras : [empresaId]).filter((id) => seriesDe(id).length > 0), [emisoras, empresaId, seriesDe])
  const serieEmpresa = useMemo(() => Object.fromEntries(empresasConSeries.map((id) => [id, seriesDe(id).some((x) => String(x.id) === String(b.serieEmpresa?.[id])) ? b.serieEmpresa[id] : seriesDe(id)[0].id])), [empresasConSeries, seriesDe, b.serieEmpresa])
  const bSerie = useMemo(() => ({ ...b, serieEmpresa, facturarPor }), [b, serieEmpresa, facturarPor])
  const cuerpoPrevio = useMemo(() => cuerpoCarrito(bSerie, { empresa: empresaId, conInicial: true, sucursal }), [bSerie, empresaId, sucursal])
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

  const totalCts = calculo && !calculando && !errorDeCalculo ? Math.round(Number(calculo.total) * 100) : 0

  // Un solo cobro «automático» acompaña al total mientras la persona no escriba otro monto.
  // Al contado el cobro empieza con una fila (efectivo si se puede) que acompaña al total; se guarda al tocarla.
  const cobros = useMemo(() => {
    if (credito) return b.cobros
    if (b.cobros.length === 0) {
      const medio = totalCts > 0 ? medioPorDefecto(config.medios_pago, config, b.moneda, emisoras) : null
      return medio ? [{ id: 'inicial', medio: medio.id, monto: aDinero(totalCts), referencia: '', recibido: '', auto: true }] : []
    }
    return b.cobros.length === 1 && b.cobros[0].auto ? [{ ...b.cobros[0], monto: aDinero(totalCts) }] : b.cobros
  }, [b.cobros, b.moneda, totalCts, credito, config, emisoras])

  const agregar = useCallback(
    (ficha) => {
      const r = agregarAlCarrito(b.lineas, ficha, candidatas, empresaId)
      setAviso(r.aviso)
      if (r.lineas !== b.lineas) setB((previo) => ({ ...previo, lineas: r.lineas }))
    },
    [b.lineas, candidatas, empresaId],
  )

  const listaCredito = config.listas.find((l) => l.id === config.credito.lista)
  const lista = credito ? listaCredito : config.listas.find((l) => l.id === b.lista)
  const errores = validarVenta({ lineas: b.lineas, totalCts, cobros, medios: config.medios_pago, cliente: b.cliente, tipo: b.tipo, avisosServidor: calculo?.avisos, formaPago: b.formaPago, cuotas: b.cuotas, hoy })
  const cuerpo = useMemo(() => (errores.length === 0 && !calculando && !errorDeCalculo ? cuerpoVenta({ ...bSerie, cobros }, { empresa: empresaId, vendedorPropio: config.vendedor.id, sucursal }) : null), [bSerie, cobros, empresaId, sucursal, config.vendedor.id, errores.length, calculando, errorDeCalculo])
  const clave = useClaveIdempotente(cuerpo)
  const huella = useMemo(() => JSON.stringify([cuerpoPrevio, cobros]), [cuerpoPrevio, cobros])
  const general = fallo.huella === huella ? fallo.texto : ''

  const registrar = useMutacion({
    mutationFn: ({ datos, llave }) => api.post('/ventas/', datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['ventas'], ['caja'], ['almacen'], ['inventario'], ['stock']],
    alExito: (venta) => setHecha(venta),
    avisarError: false,
  })
  const enviando = registrar.isPending

  const sinTerminar = !hecha && b.lineas.length > 0
  useEffect(() => {
    if (!sinTerminar) return undefined
    const avisar = (ev) => ev.preventDefault()
    window.addEventListener('beforeunload', avisar)
    return () => window.removeEventListener('beforeunload', avisar)
  }, [sinTerminar])

  const cobrar = () => {
    if (enviando) return
    setIntento(true)
    setFallo({ texto: '', huella })
    if (!cuerpo) return
    registrar.mutate({ datos: cuerpo, llave: clave }, { onError: (error) => setFallo({ texto: Object.keys(erroresDeCampo(error)).length ? 'Revise los datos de la venta.' : mensajeDeError(error), huella }) })
  }
  const nueva = () => {
    setHecha(null)
    setB(borradorInicial(config, hoy))
    setIntento(false)
    setFallo({ texto: '', huella: '' })
    setAviso('')
  }

  const cambiarLinea = (nueva) => setB((previo) => ({ ...previo, lineas: previo.lineas.map((l) => (l.id === nueva.id ? nueva : l)) }))
  const quitarLinea = (id) => setB((previo) => ({ ...previo, lineas: previo.lineas.filter((l) => l.id !== id) }))
  const cambiarLista = (id) => setB((previo) => ({ ...previo, lista: Number(id), lineas: previo.lineas.map((l) => ({ ...l, precio: '' })) }))
  const cambiarMoneda = (moneda) => setB((previo) => ({ ...previo, moneda, tipoCambioManual: false, tipoCambio: config.tipo_cambio?.compra ?? '', cobros: [], lineas: previo.lineas.map((l) => ({ ...l, precio: '' })) }))

  const cambiarForma = (formaPago) => setB((previo) => ({ ...previo, formaPago, cobros: [], lineas: previo.lineas.map((l) => ({ ...l, precio: '' })) }))
  const ponerCuotas = (campo, valor) => setB((previo) => ({ ...previo, cuotas: { ...previo.cuotas, [campo]: valor } }))
  // Lo que queda a crédito: el total menos el pago inicial.
  const creditoCts = Math.max(totalCts - totalCobrado(cobros), 0)
  const situacion = calculo?.cliente_credito
  const creditoEnSoles = (creditoCts / 100) * (b.moneda === 'USD' ? Number(calculo?.tipo_cambio ?? 1) : 1)
  const pasaDelLimite = credito && situacion && !situacion.sin_limite && creditoEnSoles > Number(situacion.disponible)
  const tipoDisponible = (codigo) => emisoras.every((id) => config.empresas.find((e) => e.id === id)?.tipos.includes(codigo))
  const enCarrito = useMemo(() => new Set(b.lineas.map((l) => l.ficha.id)), [b.lineas])
  const simbolo = b.moneda === 'USD' ? 'US$' : 'S/'
  const mensajes = intento ? errores : []

  return (
    <div className="pos-layout">
      {proforma && (
        <p className="compra-aviso" role="status">
          Vendiendo la proforma N° {proforma.numero_completo} de {proforma.cliente?.nombre ?? proforma.cliente_nombre}
          {proforma.vencida ? ' (ya venció: los precios se recalculan con las listas de hoy)' : ''}.
        </p>
      )}
      <div className="compra-layout">
        <div className="compra-principal">
          <PanelTarjeta icono="user" titulo="Cliente y comprobante" descripcion="A quién se vende y qué comprobante se emite. La venta siempre lleva la fecha de hoy.">
            <div className="pos-bloques">
            <div className="pos-cliente-fila">
              <ClienteVenta cliente={b.cliente} onElegir={(c) => poner('cliente', c)} disabled={enviando} obligatorio={b.tipo === '01'} />
              <div className="pos-series">
              {empresasVisibles.map((id) => {
                const lista = seriesDe(id)
                const empresa = config.empresas.find((e) => e.id === id)
                const etiqueta = config.empresas.length > 1 ? `Serie ${empresa?.letra ?? ''} · próximo N°` : 'Serie · próximo N°'
                return lista.length > 1 ? (
                  <Campo key={id} clase="pos-serie" etiqueta={etiqueta} tipo="select" requerido>
                    {(p) => (
                      <select {...p} title={`${empresa?.nombre}: elige con qué serie emitir`} value={serieEmpresa[id]} disabled={enviando} onChange={(e) => setB((previo) => ({ ...previo, serieEmpresa: { ...previo.serieEmpresa, [id]: e.target.value } }))}>
                        {lista.map((x) => (
                          <option key={x.id} value={x.id}>
                            {x.proximo}
                            {x.nombre ? ` · ${x.nombre}` : ''}
                          </option>
                        ))}
                      </select>
                    )}
                  </Campo>
                ) : (
                  <Campo key={id} clase="pos-serie" etiqueta={etiqueta}>
                    {(p) => <input {...p} title={`${empresa?.nombre}: número con el que se emitirá`} value={lista[0].proximo} readOnly disabled />}
                  </Campo>
                )
              })}
              </div>
            </div>
            {credito && b.cliente && situacion && (
              <p className={pasaDelLimite ? 'compra-aviso' : 'celda-suave'} role="status">
                {situacion.sin_limite ? (
                  <>Crédito del cliente: sin tope · debe S/ {Number(situacion.deuda).toFixed(2)}.</>
                ) : (
                  <>
                    Crédito del cliente: límite S/ {Number(situacion.limite).toFixed(2)} · debe S/ {Number(situacion.deuda).toFixed(2)} · puede comprar S/ {Number(situacion.disponible).toFixed(2)} más
                    {pasaDelLimite ? '. Esta venta pasa el límite.' : '.'}
                  </>
                )}
              </p>
            )}
            <div className="fila-campos">
              <Campo etiqueta="Comprobante" tipo="select" requerido>
                {(p) => (
                  <select {...p} value={b.tipo} disabled={enviando} onChange={(e) => poner('tipo', e.target.value)}>
                    {config.tipos_comprobante.map((t) => (
                      <option key={t.codigo} value={t.codigo} disabled={!tipoDisponible(t.codigo)}>
                        {t.nombre}
                        {tipoDisponible(t.codigo) ? '' : ' (sin serie en una empresa)'}
                      </option>
                    ))}
                  </select>
                )}
              </Campo>
              <Campo etiqueta="Fecha de la venta" icono="calendario" ayuda="Siempre es la de hoy.">
                {(p) => <input {...p} type="date" value={hoy} readOnly disabled />}
              </Campo>
            </div>
            <div className="fila-campos">
              {config.sucursales.length > 1 && (
                <Campo etiqueta="Tienda donde se vende" tipo="select">
                  {(p) => (
                    <select {...p} value={sucursal ?? ''} disabled={enviando} onChange={(e) => onSucursal(Number(e.target.value))}>
                      {config.sucursales.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.nombre}
                        </option>
                      ))}
                    </select>
                  )}
                </Campo>
              )}
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
            <CarritoVenta lineas={b.lineas} calculos={porLinea} empresas={config.empresas} candidatas={candidatas} afectaciones={config.afectaciones ?? []} moneda={b.moneda} disabled={enviando} sugerirSeries onCambiar={cambiarLinea} onQuitar={quitarLinea} />
            {b.lineas.length > 0 && (
              <button type="button" className="pos-chip peligro" disabled={enviando} onClick={() => setB((previo) => ({ ...previo, lineas: [], cobros: [] }))}>
                <Icono nombre="papelera" tam={16} /> Vaciar el carrito
              </button>
            )}
            </div>
          </PanelTarjeta>

          {permisos.venta_interna && empresasDelCarrito.length > 1 && (
            <VentaInternaVenta empresas={config.empresas} empresasDelCarrito={empresasDelCarrito} facturarPor={facturarPor} documento={b.documentoInterno} documentos={config.venta_interna?.documentos ?? []} disabled={enviando} onFacturarPor={(id) => poner('facturarPor', id)} onDocumento={(codigo) => poner('documentoInterno', codigo)} />
          )}

          <PanelTarjeta icono="wallet" titulo="Forma de pago" descripcion="Al contado se cobra ahora; a crédito se programan las cuotas y, si quieres, se cobra un pago inicial.">
            <div className="pos-bloques">
              {permisos.credito && (
                <div className="segmentos" role="radiogroup" aria-label="Forma de pago">
                  {Object.entries(FORMAS_PAGO).map(([valor, texto]) => (
                    <button key={valor} type="button" role="radio" aria-checked={b.formaPago === valor} className={b.formaPago === valor ? 'activo' : undefined} disabled={enviando} onClick={() => cambiarForma(valor)}>
                      {texto}
                    </button>
                  ))}
                </div>
              )}
              {credito && (
                <div className="pos-bloques">
                <div className="fila-campos">
                    <Campo etiqueta="Número de cuotas" ayuda="De 1 a 60. Un plazo único es 1 cuota.">
                      {(p) => <input {...p} inputMode="numeric" min={1} max={CUOTAS_MAXIMAS} value={b.cuotas.cantidad} disabled={enviando} onChange={(e) => ponerCuotas('cantidad', e.target.value.replace(/\D/g, ''))} />}
                    </Campo>
                    <Campo etiqueta="Cada" tipo="select">
                      {(p) => (
                        <select {...p} value={b.cuotas.periodicidad} disabled={enviando} onChange={(e) => ponerCuotas('periodicidad', e.target.value)}>
                          <option value="">Elige</option>
                          {config.credito.periodicidades.map((q) => (
                            <option key={q.id} value={q.id}>
                              {q.nombre}
                            </option>
                          ))}
                        </select>
                      )}
                    </Campo>
                    <Campo etiqueta="Primera cuota vence" icono="calendario">
                      {(p) => <input {...p} type="date" min={hoy} value={b.cuotas.primera} disabled={enviando} onChange={(e) => ponerCuotas('primera', e.target.value)} />}
                    </Campo>
                  </div>
                  {!b.cliente && <p className="compra-aviso">Elige al cliente: una venta a crédito siempre lleva su nombre.</p>}
                  {calculo?.comprobantes.some((c) => c.cuotas.length > 0) &&
                    calculo.comprobantes
                      .filter((c) => c.cuotas.length > 0)
                      .map((c) => {
                        const empresa = config.empresas.find((e) => e.id === c.empresa)
                        return (
                          <div key={c.empresa} className="marco-tabla compra-cronograma" aria-label={`Cronograma de ${empresa?.nombre}`}>
                            <table className="tabla-datos">
                              <caption className="celda-suave" style={{ textAlign: 'left', padding: '8px 12px' }}>
                                {calculo.comprobantes.length > 1 ? `${empresa?.nombre} · ` : ''}A crédito: {dinero(c.credito, b.moneda)}
                              </caption>
                              <thead>
                                <tr>
                                  <th className="centrado">Cuota</th>
                                  <th>Vence</th>
                                  <th className="num">Monto</th>
                                </tr>
                              </thead>
                              <tbody>
                                {c.cuotas.map((q) => (
                                  <tr key={q.numero}>
                                    <td className="centrado">{q.numero}</td>
                                    <td>{fechaCorta(q.fecha)}</td>
                                    <td className="num">{dinero(q.monto, b.moneda)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )
                      })}
                </div>
              )}
              <CobroVenta config={config} medios={config.medios_pago} cobros={cobros} credito={credito} totalCts={totalCts} moneda={b.moneda} empresasDelCarrito={emisoras} disabled={enviando || calculando} onCobros={(cobros) => poner('cobros', cobros)} />
            </div>
          </PanelTarjeta>

          <PanelTarjeta icono="documento" titulo="Observación">
            <Campo etiqueta="Nota de la venta" contador={{ actual: b.observacion.length, max: 250 }}>
              {(p) => <textarea {...p} rows={2} maxLength={250} placeholder="Opcional" value={b.observacion} disabled={enviando} onChange={(e) => poner('observacion', e.target.value)} />}
            </Campo>
          </PanelTarjeta>
        </div>

        <aside className="compra-resumen" aria-label="Resumen de la venta">
          <h3>Resumen</h3>
          <p className="celda-suave">
            {b.lineas.length} {b.lineas.length === 1 ? 'producto' : 'productos'}
            {calculo?.comprobantes.length > 1 ? ' · se emiten dos comprobantes, uno por empresa' : ''}
            {calculo?.venta_interna ? ' · un solo comprobante: la mercadería de la otra empresa pasa antes, al costo' : ''}
          </p>
          {errorDeCalculo && (
            <p role="alert" className="compra-aviso">
              {errorDeCalculo}
            </p>
          )}
          {calculo && !errorDeCalculo && (
            <div className={`pos-desglose${calculando ? ' calculando' : ''}`}>
              {calculo.comprobantes.map((c) => {
                const empresa = config.empresas.find((e) => e.id === c.empresa)
                const subtotal = Number(c.op_gravada) + Number(c.op_exonerada) + Number(c.op_inafecta)
                return (
                  <section key={c.empresa}>
                    <h4>
                      <span className="pos-insignia pequena" data-letra={empresa?.letra}>
                        {empresa?.letra}
                      </span>{' '}
                      {empresa?.nombre} <small className="celda-suave">Serie {c.serie}</small>
                    </h4>
                    <dl className="compra-totales">
                      <div>
                        <dt>Subtotal</dt>
                        <dd>{dinero(subtotal, b.moneda)}</dd>
                      </div>
                      <div>
                        <dt>IGV</dt>
                        <dd>{dinero(c.igv, b.moneda)}</dd>
                      </div>
                      <div className="compra-total">
                        <dt>Total</dt>
                        <dd>{dinero(c.total, b.moneda)}</dd>
                      </div>
                      {credito && c.credito && (
                        <div>
                          <dt>Queda a crédito</dt>
                          <dd>{dinero(c.credito, b.moneda)}</dd>
                        </div>
                      )}
                    </dl>
                  </section>
                )
              })}
            </div>
          )}
          <dl className="compra-totales" aria-busy={calculando}>
            <div className="compra-total">
              <dt>{credito ? 'Total de la venta' : 'Total a cobrar'}</dt>
              <dd aria-live="polite">{calculando ? 'Calculando…' : dinero(aDinero(totalCts), b.moneda)}</dd>
            </div>
            {credito && !calculando && totalCts > 0 && (
              <div>
                <dt>Queda a crédito</dt>
                <dd>{dinero(aDinero(creditoCts), b.moneda)}</dd>
              </div>
            )}
          </dl>
          {calculo?.avisos?.length > 0 && (
            <ul className="pos-avisos" role="status">
              {calculo.avisos.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          )}
          {mensajes.length > 0 && (
            <div className="compra-faltan">
              <strong>Para vender falta:</strong>
              <ul>
                {[...new Set(mensajes)].map((m) => (
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
          <button type="button" className="primario pos-generar" disabled={enviando || calculando || b.lineas.length === 0} onClick={cobrar}>
            <Icono nombre="documento" tam={20} />
            {enviando ? 'Registrando…' : credito ? `Generar comprobante${calculo?.comprobantes.length > 1 ? 's' : ''} a crédito` : cobros.length > 0 && totalCobrado(cobros) > 0 ? `Generar comprobante${calculo?.comprobantes.length > 1 ? 's' : ''}` : 'Cobrar y generar comprobante'}
          </button>
          <small className="celda-suave">{simbolo === 'S/' ? 'Los precios de lista no incluyen IGV: se suma al final.' : 'Los precios se convierten con el tipo de cambio de compra.'}</small>
        </aside>
      </div>

      {hecha && <VentaHechaModal venta={hecha} onNueva={nueva} />}
    </div>
  )
}

// La tienda donde se vende se recuerda en esta pestaña: sessionStorage es una comodidad, puede fallar.
const claveTienda = (empresaId) => `pos_tienda_${empresaId}`
const leerTienda = (empresaId) => {
  try {
    return Number(sessionStorage.getItem(claveTienda(empresaId))) || null
  } catch {
    return null
  }
}
const guardarTienda = (empresaId, id) => {
  try {
    sessionStorage.setItem(claveTienda(empresaId), String(id))
  } catch {
    /* sin almacenamiento disponible: se ignora */
  }
}

/** Punto de venta: vende desde una o dos empresas y emite un comprobante por cada una. */
export default function PuntoVentaPage() {
  const { empresaActivaId, empresaActiva } = useEmpresas()
  const [elegida, setElegida] = useState(() => leerTienda(empresaActivaId))
  const config = useConfiguracionVenta(empresaActivaId, elegida)
  const [params] = useSearchParams()
  const idProforma = /^\d+$/.test(params.get('proforma') ?? '') ? params.get('proforma') : ''
  const proforma = useQuery({
    queryKey: ['ventas', 'proforma-para-vender', idProforma],
    queryFn: ({ signal }) => api.get(`/ventas/proformas/${idProforma}/para-vender/`, { signal }).then((r) => r.data),
    enabled: Boolean(idProforma),
    staleTime: 0,
    retry: false,
  })
  const elegirTienda = (id) => {
    setElegida(id)
    guardarTienda(empresaActivaId, id)
  }

  return (
    <main className="listado pos-pagina">
      <CabeceraListado icono="cart" titulo="Punto de venta" descripcion={`Mostrador de ${empresaActiva?.nombre_comercial || empresaActiva?.razon_social || 'la empresa activa'}. Un solo carrito: cada producto lo surte la empresa que lo tiene y cada una emite su comprobante.`} />
      {idProforma && proforma.isError && <p className="compra-aviso" role="alert">No se pudo cargar la proforma: {mensajeDeError(proforma.error)}. Puedes armar la venta a mano.</p>}
      <EstadoConsulta consulta={config} hayDatos={Boolean(config.data) && (!idProforma || !proforma.isLoading)}>
        {config.data && (config.data.empresas.length === 0 ? <p className="estado-vacio">No tienes empresas habilitadas para vender.</p> : <Mostrador key={`${empresaActivaId}-${idProforma}`} config={config.data} empresaId={empresaActivaId} sucursal={config.sucursal} onSucursal={elegirTienda} proforma={idProforma ? proforma.data : null} />)}
      </EstadoConsulta>
    </main>
  )
}
