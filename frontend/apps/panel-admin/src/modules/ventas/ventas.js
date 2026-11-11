import { aNumero } from '../almacen/utilidades'
import { paraServidor } from '../almacen/inventario'

/** Lógica pura del punto de venta: carrito, surtidor, cobros y vuelto. El servidor revisa todo otra vez. */

export const ESTADOS_VENTA = {
  EMITIDO: { texto: 'Vigente', tono: 'verde' },
  ANULADO: { texto: 'Anulada', tono: 'rojo' },
}

/** Cómo se marca el precio de una línea según lo que calcula el servidor. */
export const ESTADOS_PRECIO = {
  OK: { texto: '', tono: '' },
  AUTORIZADO: { texto: 'Bajo el mínimo (autorizado)', tono: 'ambar' },
  BAJO_MINIMO: { texto: 'Bajo el mínimo permitido', tono: 'rojo' },
  BAJO_COSTO: { texto: 'Bajo el mínimo permitido', tono: 'rojo' },
}

export const FORMAS_PAGO = { CONTADO: 'Al contado', CREDITO: 'A crédito' }
export const CUOTAS_MAXIMAS = 60

export const numeroInterno = (venta) => String(venta.numero).padStart(6, '0')

/** Suma días a una fecha AAAA-MM-DD sin pasar por zonas horarias. */
export function sumarDias(iso, dias) {
  const [a, m, d] = iso.split('-').map(Number)
  const fecha = new Date(Date.UTC(a, m - 1, d + dias))
  return fecha.toISOString().slice(0, 10)
}

/** Lo que se puede revisar de las cuotas antes de enviar (el servidor revisa todo otra vez). */
export function erroresDeCuotas(cuotas, hoy) {
  const errores = []
  const cantidad = Number(cuotas.cantidad)
  if (!Number.isInteger(cantidad) || cantidad < 1 || cantidad > CUOTAS_MAXIMAS) errores.push(`Las cuotas deben ser de 1 a ${CUOTAS_MAXIMAS}.`)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(cuotas.primera) || cuotas.primera < hoy) errores.push('Indica cuándo vence la primera cuota (hoy o después).')
  if (!cuotas.periodicidad) errores.push('Elige cada cuánto vencen las cuotas.')
  return errores
}

const centimos = (valor) => {
  const n = aNumero(valor)
  return n === null ? null : Math.round(n * 100)
}
export const aDinero = (cts) => (cts / 100).toFixed(2)

/** Cuánto hay de un producto en una empresa (suma de sus almacenes). */
export const existenciaDe = (ficha, empresaId) => ficha.stock.filter((s) => s.empresa === empresaId).reduce((suma, s) => suma + Number(s.cantidad), 0)

/** Almacén de la empresa con más stock (el que alcanza para la cantidad, si se indica). */
export function almacenDe(ficha, empresaId, cantidad = 0) {
  const filas = ficha.stock.filter((s) => s.empresa === empresaId && Number(s.cantidad) >= cantidad)
  if (filas.length === 0) return null
  return filas.reduce((mejor, s) => (Number(s.cantidad) > Number(mejor.cantidad) ? s : mejor))
}

/** Las empresas desde las que esta persona puede surtir: todas, o solo el mostrador sin el permiso especial. */
export const empresasCandidatas = (empresas, mostradorId, puedeOtraEmpresa) => empresas.filter((e) => puedeOtraEmpresa || e.id === mostradorId)

/**
 * Quién surte un producto: la primera empresa (la principal va primero) que tiene la cantidad.
 * Un servicio no lleva stock: lo emite el mostrador. Sin stock en ninguna, no hay surtidor.
 */
export function surtidorInicial(ficha, cantidad, candidatas, mostradorId) {
  if (!ficha.controla_stock) return { empresa: mostradorId, almacen: null }
  for (const e of candidatas) {
    const almacen = almacenDe(ficha, e.id, cantidad)
    if (almacen) return { empresa: e.id, almacen: almacen.almacen }
  }
  return null
}

let contador = 0
export const lineaNueva = (ficha, surtidor) => ({ id: ++contador, ficha, empresa: surtidor.empresa, almacen: surtidor.almacen, cantidad: '1', precio: '', series: [], afectacion: '' })

/** Lo máximo que se puede vender de una línea (null en un servicio). */
export function maximoDeLinea(linea) {
  if (!linea.ficha.controla_stock) return null
  const fila = linea.ficha.stock.find((s) => s.empresa === linea.empresa && s.almacen === linea.almacen)
  return fila ? Number(fila.cantidad) : 0
}

/** Agrega un producto: si ya está de la misma empresa suma una unidad (sin pasar del stock). */
export function agregarAlCarrito(lineas, ficha, candidatas, mostradorId) {
  const existente = lineas.find((l) => l.ficha.id === ficha.id)
  if (existente) {
    const maximo = maximoDeLinea(existente)
    const nueva = (aNumero(existente.cantidad) ?? 0) + 1
    if (maximo !== null && nueva > maximo) return { lineas, aviso: `Solo hay ${maximo} de «${ficha.nombre}» en esa empresa.` }
    return { lineas: lineas.map((l) => (l === existente ? { ...l, cantidad: String(nueva) } : l)), aviso: '' }
  }
  const surtidor = surtidorInicial(ficha, 1, candidatas, mostradorId)
  if (!surtidor) return { lineas, aviso: `«${ficha.nombre}» no tiene stock.` }
  return { lineas: [...lineas, lineaNueva(ficha, surtidor)], aviso: '' }
}

/** Pasa la línea a la siguiente empresa que tenga la cantidad (A → B → A). Devuelve la misma si no hay otra. */
export function cambiarSurtidor(linea, candidatas) {
  if (!linea.ficha.controla_stock || candidatas.length < 2) return linea
  const cantidad = aNumero(linea.cantidad) ?? 1
  const posicion = candidatas.findIndex((e) => e.id === linea.empresa)
  for (let paso = 1; paso < candidatas.length; paso += 1) {
    const e = candidatas[(posicion + paso) % candidatas.length]
    const almacen = almacenDe(linea.ficha, e.id, cantidad)
    if (almacen) return { ...linea, empresa: e.id, almacen: almacen.almacen, series: [] }
  }
  return linea
}

export const precioDeLista = (ficha, listaId) => {
  const fila = ficha.precios.find((p) => p.lista === listaId)
  return fila ? Number(fila.precio) : null
}

/** ¿Se puede vender este producto con esa lista? */
export const tienePrecio = (ficha, listaId) => (precioDeLista(ficha, listaId) ?? 0) > 0

/** Normaliza lo escrito en el cuadro de series: una por línea o separadas por coma. */
export const parsearSeriesDeVenta = (texto) => [...new Set(String(texto ?? '').split(/[\n,;]+/).map((s) => s.trim().replace(/\s+/g, ' ').toUpperCase()).filter(Boolean))]

/** Cuerpo para calcular o guardar: solo las líneas con cantidad válida. */
export function cuerpoCarrito(b, { empresa, conInicial = false, sucursal = null }) {
  const lineas = b.lineas
    .filter((l) => (aNumero(l.cantidad) ?? 0) > 0)
    .map((l) => ({
      producto: l.ficha.id,
      cantidad: paraServidor(l.cantidad),
      empresa: l.empresa,
      ...(l.almacen ? { almacen: l.almacen } : {}),
      ...(l.precio !== '' && aNumero(l.precio) !== null ? { precio_unitario: paraServidor(l.precio) } : {}),
      ...(l.series.length ? { series: l.series } : {}),
      ...(l.afectacion ? { afectacion: l.afectacion } : {}),
    }))
  const cuerpo = { empresa, tipo_comprobante: b.tipo, moneda: b.moneda, lineas }
  const enCarrito = new Set(b.lineas.map((l) => String(l.empresa)))
  const series = Object.entries(b.serieEmpresa ?? {}).filter(([e]) => enCarrito.has(String(e)))
  if (series.length) cuerpo.serie_por_empresa = Object.fromEntries(series.map(([e, id]) => [e, Number(id)]))
  if (sucursal) cuerpo.sucursal = sucursal
  // Venta interna: un solo comprobante, de esta empresa, con la mercadería de la otra pasada al costo.
  if (b.facturarPor) {
    cuerpo.facturar_por = b.facturarPor
    cuerpo.documento_interno = b.documentoInterno || 'INTERNO'
  }
  if (b.cliente) cuerpo.cliente = b.cliente.id
  if (b.formaPago === 'CREDITO') {
    // A crédito el servidor usa la lista de crédito sola.
    cuerpo.forma_pago = 'CREDITO'
    if (b.cuotas.cantidad && b.cuotas.primera && b.cuotas.periodicidad) {
      cuerpo.cuotas = { cantidad: Number(b.cuotas.cantidad) || 1, primera_fecha: b.cuotas.primera, periodicidad: Number(b.cuotas.periodicidad) }
    }
    if (conInicial && totalCobrado(b.cobros) > 0) cuerpo.inicial = aDinero(totalCobrado(b.cobros))
  } else if (b.lista) {
    cuerpo.lista = b.lista
  }
  // Solo se envía el tipo de cambio si quien vende lo cambió a mano (para eso necesita permiso).
  if (b.moneda === 'USD' && b.tipoCambioManual && b.tipoCambio !== '') cuerpo.tipo_cambio = paraServidor(b.tipoCambio)
  return cuerpo
}

// --- Cobros -------------------------------------------------------------------------------------
let contadorCobros = 0
// `auto`: el primer cobro acompaña al total mientras la persona no escriba otro monto.
export const cobroNuevo = (medio, monto, auto = false) => ({ id: ++contadorCobros, medio, monto: aDinero(monto), referencia: '', recibido: '', auto })

/** ¿Entra este método a una caja o cuenta de TODAS las empresas del carrito? Si no, por qué. */
export function disponibilidadDeCobro(medio, config, moneda, empresasDelCarrito) {
  for (const id of empresasDelCarrito) {
    const estado = config.cobros[moneda]?.[String(id)]?.[String(medio.id)]
    if (!estado?.ok) {
      const empresa = config.empresas.find((e) => e.id === id)
      return { ok: false, motivo: estado?.motivo ?? `${empresa?.nombre ?? 'La empresa'} no tiene dónde recibir este cobro.` }
    }
  }
  return { ok: true }
}

/** El método con que empieza un cobro al contado: efectivo si entra en todas las empresas; si no, el primero que entre. */
export function medioPorDefecto(medios, config, moneda, empresasDelCarrito) {
  const sirven = medios.filter((m) => disponibilidadDeCobro(m, config, moneda, empresasDelCarrito).ok)
  return sirven.find((m) => m.tipo === 'EFECTIVO') ?? sirven[0]
}

export const totalCobrado = (cobros) => cobros.reduce((suma, c) => suma + (centimos(c.monto) ?? 0), 0)
export const faltaCobrar = (totalCts, cobros) => totalCts - totalCobrado(cobros)

/** Atajos de billetes: los que alcanzan para pagar el monto (o el siguiente múltiplo de 100). */
export function atajosDeBilletes(montoCts) {
  const monto = montoCts / 100
  const billetes = [50, 100, 200, 500].filter((b) => b >= monto)
  return billetes.length ? billetes : [Math.ceil(monto / 100) * 100]
}

/** El vuelto de un cobro en efectivo (en céntimos): lo recibido menos lo cobrado; nunca negativo. */
export function vueltoDe(cobro) {
  const recibido = centimos(cobro.recibido)
  const monto = centimos(cobro.monto) ?? 0
  return recibido === null || recibido < monto ? 0 : recibido - monto
}

/** Errores que se pueden ver antes de guardar (el servidor revisa todo otra vez). */
export function validarVenta({ lineas, totalCts, cobros, medios, cliente, tipo, avisosServidor, formaPago = 'CONTADO', cuotas, hoy }) {
  const errores = []
  if (lineas.length === 0) errores.push('Agrega al menos un producto.')
  for (const l of lineas) {
    const cantidad = aNumero(l.cantidad)
    if (cantidad === null || cantidad <= 0) errores.push(`«${l.ficha.nombre}»: indica la cantidad.`)
    const maximo = maximoDeLinea(l)
    if (cantidad !== null && maximo !== null && cantidad > maximo) errores.push(`«${l.ficha.nombre}»: solo hay ${maximo}.`)
    if (l.ficha.lleva_serie && l.series.length !== cantidad) errores.push(`«${l.ficha.nombre}»: registra ${cantidad ?? 'las'} serie(s).`)
  }
  if (tipo === '01' && !(cliente && cliente.tipo_documento === 'RUC')) errores.push('Para una factura elige un cliente con RUC.')
  const credito = formaPago === 'CREDITO'
  if (credito) {
    if (!cliente) errores.push('Una venta a crédito necesita un cliente identificado.')
    if (cuotas) errores.push(...erroresDeCuotas(cuotas, hoy))
  } else if (cobros.length === 0) errores.push('Indica cómo paga el cliente.')
  for (const c of cobros) {
    const medio = medios.find((m) => m.id === c.medio)
    if ((centimos(c.monto) ?? 0) <= 0) errores.push(`Cobro con ${medio?.nombre ?? 'el método'}: indica el monto.`)
    if (medio?.requiere_referencia && !c.referencia.trim()) errores.push(`Cobro con ${medio.nombre}: indica el número de operación.`)
    if (medio?.tipo === 'EFECTIVO' && c.recibido !== '' && (centimos(c.recibido) ?? 0) < (centimos(c.monto) ?? 0)) errores.push('El efectivo recibido no alcanza.')
  }
  if (credito) {
    if (totalCts > 0 && faltaCobrar(totalCts, cobros) <= 0) errores.push('El pago inicial debe ser menor que el total: si paga todo, véndelo al contado.')
  } else if (cobros.length && faltaCobrar(totalCts, cobros) !== 0) errores.push(faltaCobrar(totalCts, cobros) > 0 ? 'Falta cobrar una parte del total.' : 'Los cobros pasan del total.')
  return [...errores, ...(avisosServidor ?? [])]
}

/**
 * La empresa que emite el único comprobante de una venta interna, o null si no aplica: hace falta el
 * permiso, que el carrito mezcle las dos empresas y que la elegida tenga productos en él.
 */
export const facturadoraEfectiva = (facturarPor, empresasDelCarrito, puede) => (puede && empresasDelCarrito.length > 1 && empresasDelCarrito.includes(facturarPor) ? facturarPor : null)

/** Cuerpo de la venta: el carrito más quién vende, cómo pagó el cliente y la nota. */
export function cuerpoVenta(b, { empresa, vendedorPropio, sucursal = null }) {
  const cuerpo = cuerpoCarrito(b, { empresa, sucursal })
  if (b.proforma) cuerpo.proforma = b.proforma
  cuerpo.cobros = b.cobros.map((c) => ({
    medio_pago: c.medio,
    monto: paraServidor(c.monto),
    ...(c.referencia.trim() ? { referencia: c.referencia.trim() } : {}),
    ...(c.recibido !== '' ? { recibido: paraServidor(c.recibido) } : {}),
  }))
  if (b.vendedor && b.vendedor !== vendedorPropio) cuerpo.vendedor = b.vendedor
  if (b.observacion.trim()) cuerpo.observacion = b.observacion.trim()
  return cuerpo
}

/** La periodicidad «Mensual» si existe; si no, la primera. */
export const periodicidadInicial = (config) => {
  const lista = config.credito?.periodicidades ?? []
  return (lista.find((p) => p.nombre.toLowerCase() === 'mensual') ?? lista[0])?.id
}

export const borradorInicial = (config, hoy) => ({
  lineas: [],
  cliente: null,
  // Lo más común en mostrador: boleta (si no está disponible, la nota de venta o la primera)
  tipo: ['03', 'NV'].find((c) => config.tipos_comprobante.some((t) => t.codigo === c)) ?? (config.tipos_comprobante[0]?.codigo ?? ''),
  serieEmpresa: {}, // serie elegida por empresa cuando hay varias del mismo tipo
  facturarPor: null, // venta interna: empresa que emite el único comprobante (vacío = uno por empresa)
  documentoInterno: 'INTERNO',
  lista: config.listas.find((l) => l.es_principal)?.id ?? null,
  formaPago: 'CONTADO',
  cuotas: { cantidad: '3', primera: sumarDias(hoy, 30), periodicidad: String(periodicidadInicial(config) ?? '') },
  moneda: 'PEN',
  tipoCambio: config.tipo_cambio?.compra ?? '',
  tipoCambioManual: false,
  vendedor: config.vendedor.id,
  observacion: '',
  cobros: [],
})

// --- Abonos (cobrar las cuotas de una venta a crédito) -------------------------------------------

/** Errores que se pueden ver antes de cobrar una cuota (el servidor revisa todo otra vez). */
export function validarAbonos({ cobros, medios, saldoCts }) {
  const errores = []
  if (cobros.length === 0) errores.push('Elige cómo paga el cliente.')
  for (const c of cobros) {
    const medio = medios.find((m) => m.id === c.medio)
    if ((centimos(c.monto) ?? 0) <= 0) errores.push(`Cobro con ${medio?.nombre ?? 'el método'}: indica el monto.`)
    if (medio?.requiere_referencia && !c.referencia.trim()) errores.push(`Cobro con ${medio.nombre}: indica el número de operación.`)
    if (medio?.tipo === 'EFECTIVO' && c.recibido !== '' && (centimos(c.recibido) ?? 0) < (centimos(c.monto) ?? 0)) errores.push('El efectivo recibido no alcanza.')
  }
  if (totalCobrado(cobros) > saldoCts) errores.push('Los abonos pasan de lo que se debe.')
  return errores
}

/** Cuerpo del abono: los cobros y, si se eligieron, las cuotas a las que se aplican. */
export function cuerpoAbonos(cobros, cuotaIds, serieRecibo = null) {
  const cuerpo = {
    abonos: cobros.map((c) => ({
      medio_pago: c.medio,
      monto: paraServidor(c.monto),
      ...(c.referencia.trim() ? { referencia: c.referencia.trim() } : {}),
      ...(c.recibido !== '' ? { recibido: paraServidor(c.recibido) } : {}),
    })),
  }
  if (cuotaIds.length) cuerpo.cuotas = cuotaIds
  if (serieRecibo) cuerpo.serie_recibo = Number(serieRecibo)
  return cuerpo
}

/** Cómo se ve una cuota: cobrada, vencida, por vencer o al día. */
export function estadoDeCuota(cuota, hoy) {
  if (Number(cuota.saldo) <= 0) return { texto: 'Cobrada', tono: 'verde' }
  if (cuota.fecha_vencimiento < hoy) return { texto: 'Vencida', tono: 'rojo' }
  if (cuota.fecha_vencimiento === hoy) return { texto: 'Vence hoy', tono: 'ambar' }
  return Number(cuota.pagado) > 0 ? { texto: 'Parcial', tono: 'ambar' } : { texto: 'Por cobrar', tono: 'gris' }
}

// --- Proformas -----------------------------------------------------------------------------------

export const ESTADOS_PROFORMA = {
  VIGENTE: { texto: 'Vigente', tono: 'verde' },
  VENCIDA: { texto: 'Vencida', tono: 'ambar' },
  VENDIDA: { texto: 'Vendida', tono: 'azul' },
  ANULADA: { texto: 'Anulada', tono: 'rojo' },
}

/** Cuerpo de la proforma: el carrito de contado más para quién es y cuánto vale. */
export function cuerpoProforma(b, { empresa, sucursal = null }, { clienteNombre, clienteDocumento, contacto, validez, condiciones }) {
  const cuerpo = cuerpoCarrito({ ...b, formaPago: 'CONTADO' }, { empresa, sucursal })
  delete cuerpo.tipo_comprobante
  delete cuerpo.forma_pago
  if (!b.cliente) {
    if (clienteNombre.trim()) cuerpo.cliente_nombre = clienteNombre.trim()
    if (clienteDocumento.trim()) cuerpo.cliente_documento = clienteDocumento.trim()
  }
  if (contacto.trim()) cuerpo.cliente_contacto = contacto.trim()
  cuerpo.validez_dias = Number(validez) || 7
  if (condiciones.trim()) cuerpo.condiciones = condiciones.trim()
  return cuerpo
}

/** Errores que se pueden ver antes de guardar la proforma (el servidor revisa todo otra vez). */
export function validarProforma({ lineas, cliente, clienteNombre, validez }) {
  const errores = []
  if (lineas.length === 0) errores.push('Agrega al menos un producto.')
  if (!cliente && clienteNombre.trim().length < 2) errores.push('Indica para quién es la proforma.')
  const dias = Number(validez)
  if (!Number.isInteger(dias) || dias < 1 || dias > 90) errores.push('La proforma vale de 1 a 90 días.')
  return errores
}

/**
 * El carrito que sale de una proforma: sus líneas con la empresa que las surtiría (la cotizada si
 * puede, o la que tenga stock) y el precio cotizado solo si difiere del de la lista.
 * `avisos` dice qué líneas no se pudieron cargar y por qué.
 */
export function borradorDeProforma(base, proforma, { candidatas, mostradorId, puedeCredito = false }) {
  const lineas = []
  const avisos = []
  for (const ln of proforma.lineas) {
    const ficha = ln.ficha
    if (!ficha) {
      avisos.push('Un producto de la proforma ya no está disponible.')
      continue
    }
    const cantidad = aNumero(ln.cantidad) ?? 1
    const ordenadas = [...candidatas.filter((e) => e.id === ln.empresa), ...candidatas.filter((e) => e.id !== ln.empresa)]
    const surtidor = surtidorInicial(ficha, cantidad, ordenadas, mostradorId)
    if (!surtidor) {
      avisos.push(`«${ficha.nombre}» no tiene stock suficiente para ${cantidad}.`)
      continue
    }
    const linea = lineaNueva(ficha, surtidor)
    linea.cantidad = String(cantidad)
    if (Math.round(Number(ln.precio_unitario) * 100) !== Math.round(Number(ln.precio_lista) * 100)) linea.precio = String(Number(ln.precio_unitario))
    lineas.push(linea)
  }
  return {
    borrador: { ...base, lineas, cliente: proforma.cliente ?? null, moneda: proforma.moneda, proforma: proforma.id, tipoCambioManual: false, formaPago: proforma.forma_pago === 'CREDITO' && puedeCredito ? 'CREDITO' : base.formaPago },
    avisos,
  }
}

// --- Notas de crédito ----------------------------------------------------------------------------

/** Los motivos que devuelven todo lo que queda del comprobante, sin elegir cantidades. */
export const MOTIVOS_TOTALES = ['01', '06']

/** Lo que devuelve cada línea según el motivo: todo lo que queda (motivos totales) o lo que se escribió. */
export function cantidadesDeMotivo(motivo, lineas, escritas) {
  if (!MOTIVOS_TOTALES.includes(motivo)) return escritas
  return Object.fromEntries(lineas.filter((l) => Number(l.disponible) > 0).map((l) => [l.id, String(Number(l.disponible))]))
}

/** Las series que vuelven: en un motivo total, todas las que quedan; si no, las elegidas. */
export function seriesDeMotivo(motivo, lineas, elegidas) {
  if (!MOTIVOS_TOTALES.includes(motivo)) return elegidas
  return Object.fromEntries(lineas.filter((l) => l.lleva_serie).map((l) => [l.id, l.series]))
}

/**
 * El reembolso que se propone: por los mismos métodos con que pagó el cliente. Si parte del dinero no
 * cabe en lo que pagó (`sinAsignar`), va en otra fila con el método por omisión para que la persona la ajuste.
 */
export function cobrosSugeridos(sugerido, sinAsignar, medioPorOmision) {
  const filas = sugerido.map((s) => cobroNuevo(s.medio_pago, Math.round(Number(s.monto) * 100)))
  const resto = Math.round(Number(sinAsignar) * 100)
  if (resto > 0 && medioPorOmision) filas.push(cobroNuevo(medioPorOmision, resto))
  return filas
}

/** Las líneas elegidas: cantidad mayor que cero, con las series si la línea las lleva. */
export function lineasDevueltas(lineas, cantidades, series) {
  return lineas
    .filter((l) => (aNumero(cantidades[l.id]) ?? 0) > 0)
    .map((l) => ({
      linea: l.id,
      cantidad: paraServidor(cantidades[l.id]),
      ...(l.lleva_serie ? { series: series[l.id] ?? [] } : {}),
    }))
}

/** Lo que se puede revisar antes de emitir la nota (el servidor revisa todo otra vez). */
export function validarNota({ lineas, cantidades, series, cobros, medios, aReembolsarCts }) {
  const errores = []
  const elegidas = lineas.filter((l) => (aNumero(cantidades[l.id]) ?? 0) > 0)
  if (elegidas.length === 0) errores.push('Elige qué se devuelve.')
  for (const l of lineas) {
    const n = aNumero(cantidades[l.id]) ?? 0
    if (n > Number(l.disponible)) errores.push(`«${l.descripcion}»: solo se pueden devolver ${Number(l.disponible)}.`)
    if (n > 0 && l.lleva_serie && (series[l.id] ?? []).length !== n) errores.push(`«${l.descripcion}»: elige ${n} serie(s).`)
  }
  for (const c of cobros) {
    const medio = medios.find((m) => m.id === c.medio)
    if ((centimos(c.monto) ?? 0) <= 0) errores.push(`Reembolso con ${medio?.nombre ?? 'el método'}: indica el monto.`)
    if (medio?.requiere_referencia && !c.referencia.trim()) errores.push(`Reembolso con ${medio.nombre}: indica el número de operación.`)
  }
  if (totalCobrado(cobros) !== aReembolsarCts) errores.push(aReembolsarCts > 0 ? 'Los reembolsos deben sumar lo que se devuelve en dinero.' : 'No hay nada que reembolsar: quita los reembolsos.')
  return errores
}

/**
 * Cuerpo de la nota: el motivo, lo devuelto (solo en «por ítem»; los motivos totales lo calcula el
 * servidor) y cómo se reembolsa. `serie` es la serie elegida de la nota, si hubo que elegir.
 */
export function cuerpoNota({ lineas, cantidades, series, cobros, reingresa, descripcion, motivo, serie }) {
  const cuerpo = { motivo, reingresa_stock: reingresa }
  if (!MOTIVOS_TOTALES.includes(motivo)) cuerpo.lineas = lineasDevueltas(lineas, cantidades, series)
  if (serie) cuerpo.serie_nota = Number(serie)
  if (cobros.length) {
    cuerpo.reembolsos = cobros.map((c) => ({
      medio_pago: c.medio,
      monto: paraServidor(c.monto),
      ...(c.referencia.trim() ? { referencia: c.referencia.trim() } : {}),
    }))
  }
  if (descripcion.trim()) cuerpo.descripcion = descripcion.trim()
  return cuerpo
}

/** Lo que dice el QR de los tickets: la dirección, el RUC y el celular de quien vende. */
export const textoDelQr = ({ local, ruc, telefono }) =>
  [local && `Dirección: ${local}`, ruc && `RUC: ${ruc}`, telefono && `Celular: ${telefono}`].filter(Boolean).join('\n')

// --- Importe en letras (hoja A4 del comprobante) ---------------------------------------------------

const UNIDADES = ['', 'UNO', 'DOS', 'TRES', 'CUATRO', 'CINCO', 'SEIS', 'SIETE', 'OCHO', 'NUEVE', 'DIEZ', 'ONCE', 'DOCE', 'TRECE', 'CATORCE', 'QUINCE', 'DIECISÉIS', 'DIECISIETE', 'DIECIOCHO', 'DIECINUEVE', 'VEINTE']
const VEINTI = { 1: 'VEINTIUNO', 2: 'VEINTIDÓS', 3: 'VEINTITRÉS', 6: 'VEINTISÉIS' }
const DECENAS = ['', '', '', 'TREINTA', 'CUARENTA', 'CINCUENTA', 'SESENTA', 'SETENTA', 'OCHENTA', 'NOVENTA']
const CENTENAS = ['', 'CIENTO', 'DOSCIENTOS', 'TRESCIENTOS', 'CUATROCIENTOS', 'QUINIENTOS', 'SEISCIENTOS', 'SETECIENTOS', 'OCHOCIENTOS', 'NOVECIENTOS']
const MONEDAS_EN_LETRAS = { PEN: 'SOLES', USD: 'DÓLARES AMERICANOS' }

const hasta99 = (n) => {
  if (n <= 20) return UNIDADES[n]
  const d = Math.floor(n / 10)
  const u = n % 10
  if (d === 2) return VEINTI[u] ?? `VEINTI${UNIDADES[u]}`
  return u ? `${DECENAS[d]} Y ${UNIDADES[u]}` : DECENAS[d]
}
const hasta999 = (n) => {
  if (n === 100) return 'CIEN'
  const c = Math.floor(n / 100)
  const r = n % 100
  return [c ? CENTENAS[c] : '', r ? hasta99(r) : ''].filter(Boolean).join(' ')
}
// Delante de «mil» y «millones», «uno» se apocopa: «veintiún mil», «treinta y un mil».
const apocopado = (texto) => texto.replace(/VEINTIUNO$/, 'VEINTIÚN').replace(/UNO$/, 'UN')

const enLetras = (n) => {
  if (n === 0) return 'CERO'
  const millones = Math.floor(n / 1_000_000)
  const miles = Math.floor((n % 1_000_000) / 1000)
  const resto = n % 1000
  return [millones ? (millones === 1 ? 'UN MILLÓN' : `${apocopado(hasta999(millones))} MILLONES`) : '', miles ? (miles === 1 ? 'MIL' : `${apocopado(hasta999(miles))} MIL`) : '', resto ? hasta999(resto) : ''].filter(Boolean).join(' ')
}

/** «DIEZ 00/100 SOLES»: el importe como se escribe en un comprobante (hasta 999 999 999,99). */
export function importeEnLetras(total, moneda) {
  const centimosTotales = Math.round(Number(total) * 100)
  if (!Number.isFinite(centimosTotales) || centimosTotales < 0 || centimosTotales >= 100_000_000_000) return ''
  const entero = Math.floor(centimosTotales / 100)
  const fraccion = String(centimosTotales % 100).padStart(2, '0')
  return `${enLetras(entero)} ${fraccion}/100 ${MONEDAS_EN_LETRAS[moneda] ?? ''}`.trim()
}

// --- Guías de remisión ---------------------------------------------------------------------------

/** Los motivos del traslado; por ahora solo la venta se hace desde un comprobante (los otros llegan después). */
export const MOTIVOS_GUIA = [
  { codigo: '01', nombre: 'Venta', disponible: true },
  { codigo: '04', nombre: 'Traslado entre establecimientos de la misma empresa', disponible: false },
  { codigo: '13', nombre: 'Otros', disponible: false },
]
export const MAX_VEHICULOS_SECUNDARIOS = 5

const miligramos = (valor) => Math.round((aNumero(valor) ?? 0) * 1000)

/** Lo que se envía: las líneas con cantidad mayor que cero. */
const conCantidad = (lineas, cantidades) => lineas.filter((l) => (aNumero(cantidades[l.id]) ?? 0) > 0)

/** Los kilos de lo que se envía: la suma de los pesos de las líneas elegidas (sin errores de redondeo). */
export function sumaPesos(lineas, cantidades, pesos) {
  return conCantidad(lineas, cantidades).reduce((suma, l) => suma + miligramos(pesos[l.id]), 0) / 1000
}

/** Las líneas elegidas en el formato del servidor; el peso se envía solo si se escribió. */
export function lineasDeGuia(lineas, cantidades, pesos) {
  return conCantidad(lineas, cantidades).map((l) => ({
    linea: l.id,
    cantidad: paraServidor(cantidades[l.id]),
    ...(String(pesos[l.id] ?? '').trim() ? { peso_kg: paraServidor(pesos[l.id]) } : {}),
  }))
}

/** Hasta 3 decimales y no negativo (el servidor revisa todo otra vez). */
const pesoValido = (valor) => {
  const n = aNumero(valor)
  return n !== null && n >= 0 && Math.abs(n * 1000 - Math.round(n * 1000)) < 1e-6
}

/** Los kilos de todos los productos de un traspaso (que viajan completos), sin errores de redondeo. */
export function sumaPesosDe(lineas, pesos) {
  return lineas.reduce((suma, l) => suma + miligramos(pesos[l.id]), 0) / 1000
}

/** Lo que se revisa en toda guía, sea de una venta o de un traspaso: lugares, fecha, transporte, carga y serie. */
function validarEnvio({ f, hoy, series, serie }) {
  const errores = []
  if (f.partida.trim().length < 5) errores.push('Indica el punto de partida.')
  if (f.llegada.trim().length < 5) errores.push('Indica el punto de llegada.')
  if (!/^\d{4}-\d{2}-\d{2}$/.test(f.fechaTraslado) || f.fechaTraslado < hoy) errores.push('La fecha de traslado no puede ser anterior a hoy.')
  if (f.modalidad === '01' && !f.transportista) errores.push('Elige la empresa de transporte.')
  if (f.modalidad === '02' && !f.m1l) {
    if (!f.conductor) errores.push('Elige el conductor (o marca el traslado en vehículo M1 o L).')
    if (!f.vehiculo) errores.push('Elige el vehículo (o marca el traslado en vehículo M1 o L).')
  }
  if (f.vehiculo && f.secundarios.includes(f.vehiculo)) errores.push('El vehículo principal no puede ser también secundario.')
  if (!/^\d+$/.test(String(f.bultos).trim()) || Number(f.bultos) < 1) errores.push('Los bultos son un número entero mayor que cero.')
  if (String(f.pesoEscrito).trim() && !pesoValido(f.pesoEscrito)) errores.push('El peso total admite hasta 3 decimales y no puede ser negativo.')
  if (series.length === 0) errores.push('No hay una serie de guía de remisión: créala en Mantenimiento → Series de comprobantes.')
  else if (!serie) errores.push('Elige la serie de la guía.')
  return errores
}

/**
 * Lo que se puede revisar antes de emitir la guía. `f` es el formulario (ver `useGuiaRemision`);
 * `series` son las series posibles de la guía y `hoy` la fecha de hoy (AAAA-MM-DD).
 */
export function validarGuia({ lineas, cantidades, pesos, f, hoy, series, serie }) {
  const errores = []
  if (conCantidad(lineas, cantidades).length === 0) errores.push('Elige qué se envía.')
  for (const l of lineas) {
    const n = aNumero(cantidades[l.id]) ?? 0
    if (n > Number(l.pendiente)) errores.push(`«${l.descripcion}»: solo falta enviar ${Number(l.pendiente)}.`)
    if (n > 0 && String(pesos[l.id] ?? '').trim() && !pesoValido(pesos[l.id])) errores.push(`«${l.descripcion}»: el peso admite hasta 3 decimales y no puede ser negativo.`)
  }
  return [...errores, ...validarEnvio({ f, hoy, series, serie })]
}

/** Lo mismo para la guía de un traspaso: viaja todo lo traspasado, así que de los productos solo se revisan los pesos. */
export function validarGuiaTraslado({ lineas, pesos, f, hoy, series, serie }) {
  const errores = lineas.filter((l) => String(pesos[l.id] ?? '').trim() && !pesoValido(pesos[l.id])).map((l) => `«${l.descripcion}»: el peso admite hasta 3 decimales y no puede ser negativo.`)
  return [...errores, ...validarEnvio({ f, hoy, series, serie })]
}

/**
 * La parte del cuerpo que toda guía lleva. El transporte público lleva a la empresa de transporte (y el
 * conductor y el vehículo solo si se registraron); el privado, el conductor y el vehículo elegidos.
 */
function cuerpoDeEnvio({ f, serie }) {
  const publico = f.modalidad === '01'
  const conChofer = !publico || f.conductorEnPublico
  const cuerpo = {
    fecha_traslado: f.fechaTraslado,
    modalidad: f.modalidad,
    punto_partida: f.partida.trim(),
    punto_llegada: f.llegada.trim(),
    traslado_m1_l: Boolean(f.m1l),
    bultos: Number(f.bultos),
  }
  if (f.ubigeoPartida) cuerpo.ubigeo_partida = f.ubigeoPartida
  if (f.ubigeoLlegada) cuerpo.ubigeo_llegada = f.ubigeoLlegada
  if (serie) cuerpo.serie_guia = Number(serie)
  if (publico) cuerpo.transportista = Number(f.transportista)
  if (conChofer && f.conductor) cuerpo.conductor = Number(f.conductor)
  if (conChofer && f.vehiculo) cuerpo.vehiculo = Number(f.vehiculo)
  if (conChofer && f.vehiculo && f.secundarios.length) cuerpo.vehiculos_secundarios = f.secundarios.map(Number)
  if (String(f.pesoEscrito).trim()) cuerpo.peso_kg = paraServidor(f.pesoEscrito)
  if (f.observacion.trim()) cuerpo.observacion = f.observacion.trim()
  return cuerpo
}

/**
 * Cuerpo de la guía de una venta. El destinatario solo se envía si se cambió el cliente de la venta.
 */
export function cuerpoGuia({ lineas, cantidades, pesos, f, destinatario, serie }) {
  const cuerpo = { lineas: lineasDeGuia(lineas, cantidades, pesos), ...cuerpoDeEnvio({ f, serie }) }
  if (destinatario) cuerpo.destinatario = destinatario.id
  return cuerpo
}

/** Cuerpo de la guía de un traspaso: el motivo y, de los productos, solo los pesos que se escribieron. */
export function cuerpoGuiaTraslado({ lineas, pesos, f, serie }) {
  const cuerpo = { motivo: f.motivo, ...cuerpoDeEnvio({ f, serie }) }
  const conPeso = lineas.filter((l) => String(pesos[l.id] ?? '').trim())
  if (conPeso.length) cuerpo.lineas = conPeso.map((l) => ({ linea: l.id, peso_kg: paraServidor(pesos[l.id]) }))
  return cuerpo
}

/** De dónde sale una guía: de una venta (con su comprobante) o de un traspaso entre almacenes. */
export function origenDeGuia(g) {
  if (g.traspaso) {
    const valor = `N° ${String(g.traspaso_numero).padStart(6, '0')}`
    return { etiqueta: 'Del traspaso', valor, corto: `Traspaso ${valor}`, tipo: 'Traslado entre almacenes' }
  }
  return { etiqueta: 'De la venta', valor: g.comprobante_numero, corto: g.comprobante_numero, tipo: g.comprobante_tipo }
}

/**
 * Quién lleva la mercadería de una guía y en qué, como pares «etiqueta, valor» listos para mostrar o imprimir.
 * En el transporte público va la empresa de transporte (con sus registros del MTC); en el privado, la propia
 * empresa. Después, si se registraron, el conductor y los vehículos. Las guías anteriores traen menos datos.
 */
export function datosDeTransporte(g) {
  const conductor = [g.conductor_nombre, g.conductor_documento, g.conductor_licencia && `Licencia ${g.conductor_licencia}`].filter(Boolean).join(' · ')
  const vehiculo = g.vehiculo_descripcion || g.placa
  const secundarias = (g.placas_secundarias ?? []).join(', ')
  const empresa = g.transportista_nombre ? `${g.transportista_nombre}${g.transportista_documento ? ` · RUC ${g.transportista_documento}` : ''}` : ''
  return [
    [g.modalidad === '01' ? 'Empresa de transporte' : 'Transportista', empresa],
    ['Registro MTC', g.transportista_mtc],
    ['Certificado de inspección', g.transportista_certificado],
    ['Conductor', conductor],
    ['Vehículo', vehiculo],
    ['Placas secundarias', secundarias],
    ['Categoría del vehículo', g.traslado_m1_l ? 'M1 o L (no se exige conductor ni placa)' : ''],
  ].filter(([, valor]) => Boolean(valor))
}

/** Una dirección con su ubigeo, si lo tiene: «Jr. Lima 123 (SAN MARTÍN - SAN MARTÍN - TARAPOTO)». */
export const lugarConUbigeo = (direccion, ubigeo) => (ubigeo ? `${direccion} (${ubigeo})` : direccion)
