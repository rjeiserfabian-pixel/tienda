// Lógica pura de la pantalla de compras: borrador, cuerpo que recibe el servidor y validaciones.
// Los importes los calcula SIEMPRE el servidor (vista previa); aquí solo se arman y se revisan datos.
import { hoyIso, numerosDe, paraServidor, serieValida } from '../almacen/inventario'
import { aNumero } from '../almacen/utilidades'

export const FORMAS_PAGO = { CONTADO: 'Contado', CREDITO: 'Crédito' }
export const MONEDAS = { PEN: { simbolo: 'S/', nombre: 'Soles' }, USD: { simbolo: 'US$', nombre: 'Dólares' } }

const FORMATO_DINERO = new Intl.NumberFormat('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** «S/ 1 234,50». Acepta el texto del servidor o un número. */
export const dinero = (valor, moneda = 'PEN') => {
  const n = aNumero(valor)
  return n === null ? '—' : `${MONEDAS[moneda]?.simbolo ?? 'S/'} ${FORMATO_DINERO.format(n)}`
}

export const numeroInterno = (compra) => String(compra.numero).padStart(6, '0')

let contador = 0
const nuevoId = () => ++contador

export const sumarDias = (iso, dias) => {
  const fecha = new Date(`${iso}T12:00:00`)
  fecha.setDate(fecha.getDate() + dias)
  return fecha.toLocaleDateString('en-CA')
}

/** Céntimos enteros: evita errores de coma flotante al comparar sumas de dinero. */
const centimos = (n) => Math.round((n ?? 0) * 100)

export const nuevoPago = () => ({ id: nuevoId(), medio: '', cuenta: '', monto: '', auto: true, referencia: '', tipoCambio: '', aporte: false })

/** Monto en otra moneda: soles → dólares divide entre el tipo de cambio; dólares → soles multiplica. */
export const convertirMoneda = (monto, de, a, tipoCambio) => {
  if (de === a) return monto
  return Math.round((de === 'PEN' ? monto / tipoCambio : monto * tipoCambio) * 100) / 100
}

export const borradorInicial = () => ({
  orden: null, // id de la orden de compra que se está recibiendo (si la hay)
  proveedor: null,
  almacen: '',
  tipo: '',
  serie: '',
  numero: '',
  fecha: hoyIso(),
  guia: '',
  observacion: '',
  moneda: 'PEN',
  tipoCambio: '',
  incluyeIgv: false,
  ajuste: '',
  forma: 'CONTADO',
  lineas: [],
  pagos: [nuevoPago()],
  cuotas: { cantidad: '1', primera: sumarDias(hoyIso(), 30), periodicidad: '' },
  flete: { activo: false, monto: '', alCosto: true, medio: '', cuenta: '', referencia: '', tipo: '', serie: '', numero: '' },
})

/** Línea nueva para un producto elegido en el buscador. */
export const lineaDeProducto = (producto) => ({
  id: nuevoId(),
  producto,
  presentacion: '',
  cantidad: '1',
  precio: '',
  afectacion: '',
  series: [],
  ubicacion: '',
  lote: '',
  precioSugerido: false, // el precio viene del costo del catálogo y aún no lo confirmó la persona
  ventaPrecios: null, // precios de venta preparados con «PV»; se aplican al registrar la compra
  lineaOrden: null, // línea de la orden de compra a la que corresponde (al recibir una orden)
})

export const presentacionesActivas = (producto) => (producto?.presentaciones ?? []).filter((p) => p.estado === 'ACTIVO')

export const cantidadDe = (linea) => (linea.producto?.lleva_serie ? linea.series.length : (aNumero(linea.cantidad) ?? 0))

/** ¿La línea tiene lo mínimo para pedir su cálculo al servidor? */
export const lineaCalculable = (l) =>
  Boolean(l.producto) && cantidadDe(l) > 0 && aNumero(l.precio) !== null && aNumero(l.precio) >= 0 && /^\d+([.,]\d{1,3})?$/.test(String(cantidadDe(l)).replace('.', ','))

// ---------------------------------------------------------------------------
// Pagos al contado
// ---------------------------------------------------------------------------
/**
 * Pagos listos para mostrar y enviar. El pago «automático» toma lo que falta para llegar al total;
 * el medio y la caja vacíos se completan con lo más probable (efectivo, y la única caja de esa moneda).
 */
export function resolverPagos(pagos, total, { medios, cuentas, moneda, tipoCambio = '' }) {
  const totalCentimos = centimos(aNumero(total))
  const fijos = pagos.filter((p) => !p.auto).reduce((s, p) => s + centimos(aNumero(p.monto)), 0)
  const medioBase = medios.find((m) => m.tipo === 'EFECTIVO') ?? medios[0]
  const cuentasDeLaMoneda = cuentas.filter((c) => c.moneda === moneda)
  return pagos.map((p) => {
    const medio = medios.some((m) => String(m.id) === String(p.medio)) ? String(p.medio) : String(medioBase?.id ?? '')
    // Se puede pagar desde una cuenta de otra moneda (con su tipo de cambio); solo se propone sola la de la misma moneda.
    const cuenta = cuentas.some((c) => String(c.id) === String(p.cuenta)) ? String(p.cuenta) : cuentasDeLaMoneda.length === 1 ? String(cuentasDeLaMoneda[0].id) : ''
    const cuentaElegida = cuentas.find((c) => String(c.id) === cuenta)
    const monto = p.auto ? (Math.max(0, totalCentimos - fijos) / 100).toFixed(2) : p.monto
    const otraMoneda = Boolean(cuentaElegida) && cuentaElegida.moneda !== moneda
    const cambio = otraMoneda ? (String(p.tipoCambio ?? '') !== '' ? p.tipoCambio : tipoCambio) : ''
    const enCuenta = otraMoneda && aNumero(cambio) > 0 && aNumero(monto) > 0 ? convertirMoneda(aNumero(monto), moneda, cuentaElegida.moneda, aNumero(cambio)) : null
    return {
      ...p,
      medio,
      cuenta,
      monto,
      pideReferencia: Boolean(medios.find((m) => String(m.id) === medio)?.requiere_referencia),
      otraMoneda,
      monedaCuenta: cuentaElegida?.moneda ?? moneda,
      tipoCambio: cambio,
      montoCuenta: enCuenta,
    }
  })
}

export const totalPagado = (pagosResueltos) => pagosResueltos.reduce((s, p) => s + centimos(aNumero(p.monto)), 0) / 100

// ---------------------------------------------------------------------------
// Cuerpo para el servidor
// ---------------------------------------------------------------------------
const cuotasValidas = (c) => {
  const cantidad = Number(c.cantidad)
  return Number.isInteger(cantidad) && cantidad >= 1 && cantidad <= 60 && Boolean(c.primera) && Boolean(c.periodicidad)
}

/**
 * Cuerpo del registro (o de la vista previa, que no lleva pagos y tolera comprobante incompleto:
 * el IGV depende del proveedor, no del número de la factura).
 * `c` trae lo ya resuelto por la pantalla: empresa, almacén, tipo de comprobante, pagos resueltos y ubicaciones válidas.
 */
export function armarCuerpo(b, c, { previa = false } = {}) {
  const lineas = b.lineas.filter((l) => !previa || lineaCalculable(l))
  const cuerpo = {
    empresa: c.empresa,
    proveedor: b.proveedor?.id ?? null,
    almacen: Number(c.almacen) || null,
    tipo_comprobante: c.tipo || (previa ? '01' : ''),
    comprobante_serie: b.serie.trim(),
    comprobante_numero: b.numero.trim() || (previa ? '0' : ''),
    fecha_emision: b.fecha,
    nro_guia: b.guia.trim(),
    observacion: b.observacion.trim(),
    moneda: b.moneda,
    precios_incluyen_igv: b.incluyeIgv,
    ajuste_redondeo: paraServidor(b.ajuste) || '0',
    forma_pago: b.forma,
    ...(b.orden ? { orden: b.orden } : {}),
    lineas: lineas.map((l) => {
      const conSerie = Boolean(l.producto.lleva_serie)
      return {
        producto: l.producto.id,
        ...(l.presentacion && !conSerie ? { presentacion: Number(l.presentacion) } : {}),
        cantidad: conSerie ? String(l.series.length) : paraServidor(l.cantidad),
        precio_unitario: paraServidor(l.precio),
        ...(l.afectacion ? { afectacion: l.afectacion } : {}),
        ...(l.lote.trim() ? { lote: l.lote.trim() } : {}),
        ...(l.lineaOrden ? { linea_orden: l.lineaOrden } : {}),
        ...(conSerie && l.series.length ? { series: l.series.map((s) => (s.otros_datos ? { numero: s.numero, otros_datos: s.otros_datos } : s.numero)) } : {}),
        ...(l.ubicacion && c.ubicacionesValidas.has(Number(l.ubicacion)) ? { ubicacion: Number(l.ubicacion) } : {}),
      }
    }),
  }
  if (b.moneda === 'USD' && b.tipoCambio) cuerpo.tipo_cambio = paraServidor(b.tipoCambio)
  if (b.forma === 'CONTADO' && !previa) {
    cuerpo.pagos = c.pagos.map((p) => ({
      medio_pago: Number(p.medio),
      cuenta: Number(p.cuenta),
      monto: paraServidor(p.monto),
      ...(p.pideReferencia || p.referencia.trim() ? { referencia: p.referencia.trim() } : {}),
      ...(p.otraMoneda ? { tipo_cambio: paraServidor(p.tipoCambio) } : {}),
      ...(p.aporte ? { aporte_socio: true } : {}),
    }))
  }
  if (b.forma === 'CREDITO' && cuotasValidas(b.cuotas)) {
    cuerpo.cuotas = { cantidad: Number(b.cuotas.cantidad), primera_fecha: b.cuotas.primera, periodicidad: Number(b.cuotas.periodicidad) }
  }
  const monto = aNumero(b.flete.monto)
  if (b.flete.activo && monto !== null && monto > 0) {
    cuerpo.flete = {
      monto: paraServidor(b.flete.monto),
      al_costo: b.flete.alCosto,
      comprobante_tipo: b.flete.tipo,
      comprobante_serie: b.flete.serie.trim(),
      comprobante_numero: b.flete.numero.trim(),
      pagos: previa
        ? []
        : [{ medio_pago: Number(c.medioFlete), cuenta: Number(c.cuentaFlete), monto: paraServidor(b.flete.monto), ...(b.flete.referencia.trim() ? { referencia: b.flete.referencia.trim() } : {}) }],
    }
  }
  return cuerpo
}

// ---------------------------------------------------------------------------
// Validación en el navegador (el servidor vuelve a validar todo)
// ---------------------------------------------------------------------------
const patronDeSerie = (tipo) => {
  try {
    return tipo?.patron_serie ? new RegExp(`^(?:${tipo.patron_serie})$`) : null
  } catch {
    return null // un patrón mal escrito en el catálogo no debe bloquear la compra: decide el servidor
  }
}

/**
 * Revisa el borrador. Devuelve los errores por campo, por línea y por pago, y `faltan`: lo que
 * impide registrar, en palabras, para el resumen.
 */
export function validarCompra(b, c, total) {
  const campos = {}
  const porLinea = {}
  const porPago = {}
  const faltan = []
  const falta = (clave, texto, mensaje) => {
    campos[clave] = mensaje ?? texto
    faltan.push(texto)
  }

  if (!b.proveedor) falta('proveedor', 'Elegir el proveedor', 'Elija el proveedor.')
  if (!c.almacen) falta('almacen', 'Elegir el almacén', 'Elija el almacén.')
  if (!c.tipo) falta('tipo', 'Elegir el tipo de comprobante', 'Elija el comprobante.')
  if (!b.numero.trim()) falta('numero', 'Escribir el número del comprobante', 'Escriba el número.')
  const patron = patronDeSerie(c.tipoCatalogo)
  if (patron && b.serie.trim() && !patron.test(b.serie.trim())) campos.serie = `No tiene el formato de ${c.tipoCatalogo.nombre}${c.tipoCatalogo.ejemplo_serie ? ` (ej. ${c.tipoCatalogo.ejemplo_serie})` : ''}.`
  if (!b.fecha) falta('fecha', 'Indicar la fecha de emisión', 'Indique la fecha.')
  else if (b.fecha > hoyIso()) falta('fecha', 'Corregir la fecha (es futura)', 'La fecha no puede ser futura.')
  const ajuste = aNumero(b.ajuste)
  if (b.ajuste !== '' && (ajuste === null || Math.abs(ajuste) > 0.1 || !/^-?\d+([.,]\d{1,2})?$/.test(b.ajuste.trim()))) campos.ajuste = 'Hasta 0.10, con dos decimales.'
  if (b.moneda === 'USD' && b.tipoCambio !== '' && !((aNumero(b.tipoCambio) ?? 0) > 0)) campos.tipoCambio = 'Mayor que cero.'

  if (b.lineas.length === 0) faltan.push('Agregar al menos un producto')
  let lineasMalas = 0
  let sinConfirmar = 0
  for (const l of b.lineas) {
    const e = {}
    if (l.producto.lleva_serie) {
      const series = numerosDe(l.series)
      const mala = series.find((s) => !serieValida(s))
      if (!series.length) e.cantidad = 'Escriba las series.'
      else if (mala) e.cantidad = `«${mala}» no es válida.`
      else if (new Set(series).size !== series.length) e.cantidad = 'Hay series repetidas.'
    } else {
      const cantidad = aNumero(l.cantidad)
      if (cantidad === null || cantidad <= 0) e.cantidad = 'Mayor que cero.'
      else if (!/^\d+([.,]\d{1,3})?$/.test(String(l.cantidad).trim())) e.cantidad = 'Hasta 3 decimales.'
    }
    const precio = aNumero(l.precio)
    if (precio === null || precio < 0) e.precio = 'Indique el precio.'
    else if (!/^\d+([.,]\d{1,6})?$/.test(String(l.precio).trim())) e.precio = 'Hasta 6 decimales.'
    if (Object.keys(e).length) lineasMalas += 1
    // Un precio que vino del catálogo se confirma con la factura antes de registrar.
    if (l.precioSugerido && !e.precio) {
      e.precio = 'Confirma el precio.'
      sinConfirmar += 1
    }
    if (Object.keys(e).length) porLinea[l.id] = e
  }
  if (sinConfirmar) faltan.push(`Confirmar ${sinConfirmar === 1 ? 'el precio de un producto' : `el precio de ${sinConfirmar} productos`} (viene del catálogo: compáralo con tu factura)`)
  if (lineasMalas) faltan.push(`Completar ${lineasMalas === 1 ? 'un producto' : `${lineasMalas} productos`} (cantidad o precio)`)

  if (b.forma === 'CONTADO') {
    c.pagos.forEach((p) => {
      const e = {}
      if (!p.medio) e.medio = 'Elija el método.'
      if (!p.cuenta) e.cuenta = 'Elija la caja o cuenta.'
      const monto = aNumero(p.monto)
      if (monto === null || monto <= 0) e.monto = 'Mayor que cero.'
      if (p.pideReferencia && !p.referencia.trim()) e.referencia = 'Indique el N° de operación.'
      if (p.otraMoneda && !(aNumero(p.tipoCambio) > 0)) e.tipoCambio = 'Indique el tipo de cambio.'
      if (Object.keys(e).length) porPago[p.id] = e
    })
    if (Object.keys(porPago).length) faltan.push('Completar el pago (método, caja o cuenta, monto)')
    else if (total !== null && centimos(totalPagado(c.pagos)) !== centimos(aNumero(total))) faltan.push('Que los pagos sumen el total de la compra')
  } else {
    const q = b.cuotas
    const cantidad = Number(q.cantidad)
    if (!Number.isInteger(cantidad) || cantidad < 1 || cantidad > 60) campos.cuotas = 'De 1 a 60 cuotas.'
    if (!q.primera) campos.primera = 'Indique la fecha.'
    else if (q.primera < b.fecha) campos.primera = 'No puede ser antes de la emisión.'
    if (!q.periodicidad) campos.periodicidad = 'Elija la periodicidad.'
    if (campos.cuotas || campos.primera || campos.periodicidad) faltan.push('Completar las cuotas del crédito')
  }

  if (b.flete.activo) {
    const monto = aNumero(b.flete.monto)
    if (monto === null || monto <= 0) campos.flete = 'Indique el monto del flete.'
    else if (!c.medioFlete || !c.cuentaFlete) campos.flete = 'Elija con qué se pagó el flete.'
    else if (c.medioFletePideReferencia && !b.flete.referencia.trim()) campos.flete = 'Indique el N° de operación del flete.'
    if (campos.flete) faltan.push('Completar el flete')
  }

  return { campos, porLinea, porPago, faltan, valido: faltan.length === 0 && Object.keys(campos).length === 0 }
}

// ---------------------------------------------------------------------------
// Precios de venta (ventana «Actualizar precios» y botón «PV» de cada línea)
// ---------------------------------------------------------------------------
/**
 * Estado editable de un producto: el costo y, por lista, el precio (el porcentaje de utilidad o de
 * margen se deriva del precio y el costo al mostrarlo). Parte de los precios guardados en el
 * producto; los `propuestos` (preparados con «PV» en la compra) mandan.
 */
export function inicialPrecios(costoUnitario, detalle, propuestos) {
  const costo = String(Number(Number(costoUnitario).toFixed(4)))
  const precios = Object.fromEntries((detalle.precios ?? []).map((x) => [x.lista, { precio: x.precio === null ? '' : String(Number(x.precio)) }]))
  for (const [lista, p] of Object.entries(propuestos ?? {})) precios[lista] = { precio: p.precio }
  return { costo, precios }
}

// ---------------------------------------------------------------------------
// Cuentas por pagar
// ---------------------------------------------------------------------------
/**
 * Cómo se aplicará un pago a las cuotas: a las elegidas, o a las pendientes; siempre de la más
 * antigua a la más nueva (la misma regla del servidor; solo sirve para mostrar el resultado antes de pagar).
 */
export function repartirPago(cuotas, monto, cuotaIds = []) {
  let restante = centimos(aNumero(monto))
  const pendientes = cuotas.filter((c) => centimos(aNumero(c.saldo)) > 0)
  const elegidas = new Set(cuotaIds.map(String))
  const candidatas = elegidas.size ? pendientes.filter((c) => elegidas.has(String(c.id))) : pendientes
  const aplicado = []
  for (const cuota of candidatas) {
    if (restante <= 0) break
    const parte = Math.min(centimos(aNumero(cuota.saldo)), restante)
    aplicado.push({ numero: cuota.numero, monto: parte / 100 })
    restante -= parte
  }
  return aplicado
}

/** Días que faltan para una fecha AAAA-MM-DD (negativo si ya pasó), contando desde hoy. */
export const diasHasta = (iso) => {
  if (!iso) return null
  const dia = 86_400_000
  return Math.round((new Date(`${iso}T12:00:00`) - new Date(`${hoyIso()}T12:00:00`)) / dia)
}

/** Estado de una cuota: pagada, pagada en parte (amortizada), pendiente o vencida. */
export function estadoCuota(cuota, compraAnulada = false) {
  const saldo = centimos(aNumero(cuota.saldo))
  const pagado = centimos(aNumero(cuota.pagado))
  if (compraAnulada) return { texto: 'Anulada', tono: 'gris' }
  if (saldo === 0) return { texto: 'Pagada', tono: 'verde' }
  const vencida = diasHasta(cuota.fecha_vencimiento) < 0
  if (pagado > 0) return { texto: vencida ? 'Pagada en parte · vencida' : 'Pagada en parte', tono: vencida ? 'rojo' : 'ambar' }
  return vencida ? { texto: 'Vencida', tono: 'rojo' } : { texto: 'Pendiente', tono: 'gris' }
}

/** Texto y color del vencimiento de una deuda: vencida, vence pronto o con tiempo. */
export function estadoVencimiento(iso) {
  const dias = diasHasta(iso)
  if (dias === null) return { texto: '—', tono: 'gris' }
  if (dias < 0) return { texto: `Vencida hace ${-dias} ${dias === -1 ? 'día' : 'días'}`, tono: 'rojo' }
  if (dias === 0) return { texto: 'Vence hoy', tono: 'ambar' }
  if (dias <= 7) return { texto: `Vence en ${dias} ${dias === 1 ? 'día' : 'días'}`, tono: 'ambar' }
  return { texto: `Vence en ${dias} días`, tono: 'gris' }
}
