// Lógica pura de las pantallas de órdenes de compra: estados, borrador, cuerpo que recibe el
// servidor y validaciones. Los importes los calcula SIEMPRE el servidor (vista previa); aquí solo
// se arman y se revisan datos.
import { hoyIso, paraServidor } from '../almacen/inventario'
import { aNumero } from '../almacen/utilidades'
import { borradorInicial, lineaDeProducto, sumarDias } from './compras'

/** Cómo se llama y se pinta cada estado de una orden. */
export const ESTADOS_ORDEN = {
  BORRADOR: { texto: 'Borrador', tono: 'gris' },
  PENDIENTE: { texto: 'Por aprobar', tono: 'ambar' },
  EMITIDA: { texto: 'Emitida', tono: 'azul' },
  PARCIAL: { texto: 'Recibida en parte', tono: 'ambar' },
  RECIBIDA: { texto: 'Recibida', tono: 'verde' },
  CERRADA: { texto: 'Cerrada', tono: 'gris' },
  ANULADA: { texto: 'Anulada', tono: 'rojo' },
}

/** Los estados en que todavía puede llegar mercadería. */
export const RECIBE = ['EMITIDA', 'PARCIAL']

/** Qué acciones admite una orden según su estado (los permisos se revisan aparte). */
export const accionesDe = (estado) => ({
  editar: estado === 'BORRADOR',
  emitir: estado === 'BORRADOR',
  aprobar: estado === 'PENDIENTE',
  rechazar: estado === 'PENDIENTE',
  reabrir: estado === 'PENDIENTE' || estado === 'EMITIDA',
  anular: ['BORRADOR', 'PENDIENTE', 'EMITIDA'].includes(estado),
  cerrar: estado === 'PARCIAL',
  recibir: RECIBE.includes(estado),
})

export const borradorOrden = () => ({
  proveedor: null,
  almacen: '',
  fecha: hoyIso(),
  entrega: '',
  observacion: '',
  moneda: 'PEN',
  tipoCambio: '',
  incluyeIgv: false,
  forma: 'CONTADO',
  plazo: '30',
  lineas: [],
})

/** ¿La línea tiene lo mínimo para pedir su cálculo al servidor? */
export const lineaCalculable = (l) => {
  const cantidad = aNumero(l.cantidad)
  const precio = aNumero(l.precio)
  return Boolean(l.producto) && cantidad !== null && cantidad > 0 && precio !== null && precio >= 0 && /^\d+([.,]\d{1,3})?$/.test(String(l.cantidad).trim())
}

/** Cuerpo de la orden (o de su vista previa, que ignora lo incompleto). */
export function armarCuerpoOrden(b, { empresa, almacen }, { previa = false } = {}) {
  const lineas = b.lineas.filter((l) => !previa || lineaCalculable(l))
  const cuerpo = {
    empresa,
    proveedor: b.proveedor?.id ?? null,
    almacen: Number(almacen) || null,
    fecha_emision: b.fecha,
    ...(b.entrega ? { fecha_entrega: b.entrega } : {}),
    moneda: b.moneda,
    precios_incluyen_igv: b.incluyeIgv,
    forma_pago: b.forma,
    plazo_dias: b.forma === 'CREDITO' ? Number(b.plazo) || 0 : 0,
    observacion: b.observacion.trim(),
    lineas: lineas.map((l) => ({
      producto: l.producto.id,
      ...(l.presentacion ? { presentacion: Number(l.presentacion) } : {}),
      cantidad: paraServidor(l.cantidad),
      precio_unitario: paraServidor(l.precio),
      ...(l.afectacion ? { afectacion: l.afectacion } : {}),
    })),
  }
  if (b.moneda === 'USD' && b.tipoCambio) cuerpo.tipo_cambio = paraServidor(b.tipoCambio)
  return cuerpo
}

/** Revisa el borrador. `faltan` es lo que impide guardar, en palabras, para el resumen. */
export function validarOrden(b, almacen) {
  const campos = {}
  const porLinea = {}
  const faltan = []
  const falta = (clave, texto, mensaje) => {
    campos[clave] = mensaje ?? texto
    faltan.push(texto)
  }
  if (!b.proveedor) falta('proveedor', 'Elegir el proveedor', 'Elija el proveedor.')
  if (!almacen) falta('almacen', 'Elegir el almacén', 'Elija el almacén.')
  if (!b.fecha) falta('fecha', 'Indicar la fecha', 'Indique la fecha.')
  else if (b.fecha > hoyIso()) falta('fecha', 'Corregir la fecha (es futura)', 'La fecha no puede ser futura.')
  if (b.entrega && b.fecha && b.entrega < b.fecha) falta('entrega', 'Corregir la fecha de entrega', 'No puede ser anterior a la emisión.')
  if (b.moneda === 'USD' && b.tipoCambio !== '' && !((aNumero(b.tipoCambio) ?? 0) > 0)) campos.tipoCambio = 'Mayor que cero.'
  if (b.forma === 'CREDITO') {
    const plazo = Number(b.plazo)
    if (!Number.isInteger(plazo) || plazo < 1 || plazo > 365) falta('plazo', 'Indicar el plazo del crédito (1 a 365 días)', 'De 1 a 365 días.')
  }
  if (b.lineas.length === 0) faltan.push('Agregar al menos un producto')
  const vistas = new Set()
  let malas = 0
  for (const l of b.lineas) {
    const e = {}
    const cantidad = aNumero(l.cantidad)
    if (cantidad === null || cantidad <= 0) e.cantidad = 'Mayor que cero.'
    else if (!/^\d+([.,]\d{1,3})?$/.test(String(l.cantidad).trim())) e.cantidad = 'Hasta 3 decimales.'
    const precio = aNumero(l.precio)
    if (precio === null || precio < 0) e.precio = 'Indique el precio.'
    else if (!/^\d+([.,]\d{1,6})?$/.test(String(l.precio).trim())) e.precio = 'Hasta 6 decimales.'
    const clave = `${l.producto.id}-${l.presentacion || 0}`
    if (vistas.has(clave)) e.cantidad = 'Producto repetido: súmalo en una línea.'
    vistas.add(clave)
    if (Object.keys(e).length) {
      porLinea[l.id] = e
      malas += 1
    }
  }
  if (malas) faltan.push(`Completar ${malas === 1 ? 'un producto' : `${malas} productos`} (cantidad o precio)`)
  return { campos, porLinea, faltan, valido: faltan.length === 0 && Object.keys(campos).length === 0 }
}

/** Del detalle de una orden al borrador de la pantalla (para editarla). `productos` por id. */
export function borradorDesdeOrden(orden, productos, proveedor) {
  return {
    proveedor,
    almacen: String(orden.almacen),
    fecha: orden.fecha_emision,
    entrega: orden.fecha_entrega ?? '',
    observacion: orden.observacion ?? '',
    moneda: orden.moneda,
    tipoCambio: orden.moneda === 'USD' ? String(Number(orden.tipo_cambio)) : '',
    incluyeIgv: orden.precios_incluyen_igv,
    forma: orden.forma_pago,
    plazo: String(orden.plazo_dias || 30),
    lineas: orden.lineas
      .filter((l) => productos[l.producto])
      .map((l) => ({
        ...lineaDeProducto(productos[l.producto]),
        presentacion: l.presentacion ? String(l.presentacion) : '',
        cantidad: String(Number(l.cantidad)),
        precio: String(Number(l.precio_unitario)),
        afectacion: l.afectacion_codigo,
      })),
  }
}

/**
 * De lo que falta recibir de una orden al borrador de «Registrar compra»: el proveedor, la moneda,
 * la forma de pago y cada producto pendiente con su precio pactado. El precio se puede corregir con
 * el de la factura (manda el del comprobante).
 */
export function borradorParaRecibir(orden, productos, proveedor) {
  const base = borradorInicial()
  const credito = orden.forma_pago === 'CREDITO'
  return {
    ...base,
    orden: orden.orden,
    proveedor,
    almacen: String(orden.almacen),
    moneda: orden.moneda,
    tipoCambio: orden.moneda === 'USD' ? String(Number(orden.tipo_cambio)) : '',
    incluyeIgv: orden.precios_incluyen_igv,
    forma: orden.forma_pago,
    cuotas: credito ? { ...base.cuotas, cantidad: '1', primera: sumarDias(hoyIso(), orden.plazo_dias || 30) } : base.cuotas,
    lineas: orden.lineas
      .filter((l) => aNumero(l.pendiente) > 0 && productos[l.producto])
      .map((l) => ({
        ...lineaDeProducto(productos[l.producto]),
        presentacion: l.presentacion ? String(l.presentacion) : '',
        cantidad: String(Number(l.pendiente)),
        precio: String(Number(l.precio_unitario)),
        afectacion: l.afectacion_codigo,
        lineaOrden: l.linea,
      })),
  }
}

/** Avance de la recepción de una orden, de 0 a 100. */
export function avance(orden) {
  const pedido = orden.lineas.reduce((s, l) => s + (aNumero(l.cantidad) ?? 0), 0)
  if (!pedido) return 0
  const recibido = orden.lineas.reduce((s, l) => s + Math.min(aNumero(l.cantidad_recibida) ?? 0, aNumero(l.cantidad) ?? 0), 0)
  return Math.round((recibido / pedido) * 100)
}

// ---------- Enviar la orden al proveedor (WhatsApp o correo) ----------
// No se envía nada desde el servidor: se abre WhatsApp o el correo del usuario con el texto
// ya escrito y es la persona quien pulsa «enviar».

/** Teléfono como lo pide WhatsApp: solo dígitos y con código de país (Perú si es un celular de 9). */
export function telefonoWhatsapp(texto) {
  let d = String(texto ?? '').replace(/\D/g, '')
  if (d.startsWith('00')) d = d.slice(2)
  if (d.length === 9 && d.startsWith('9')) d = `51${d}`
  return d.length >= 11 && d.length <= 15 ? d : null
}

/** Texto de la orden para el proveedor: productos y cantidades, entrega y total. */
export function textoOrden(o, { dinero, fechaCorta, cantidad }) {
  const emisor = o.emisor?.nombre ?? ''
  const lineas = (o.lineas ?? [])
    .map((l) => `• ${cantidad(l.cantidad)} ${l.unidad ?? ''} ${l.producto_nombre}`.replace(/\s+/g, ' '))
    .join('\n')
  return [
    `Orden de compra ${o.codigo}${emisor ? ` - ${emisor}` : ''}`,
    `Fecha: ${fechaCorta(o.fecha_emision)}`,
    o.fecha_entrega ? `Entrega esperada: ${fechaCorta(o.fecha_entrega)}` : null,
    '',
    lineas,
    '',
    `Total: ${dinero(o.total, o.moneda)}${o.precios_incluyen_igv ? ' (incluye IGV)' : ' (más IGV)'}`,
    o.observacion ? `Nota: ${o.observacion}` : null,
    '',
    'Por favor confirmar recepción y fecha de entrega. Gracias.',
  ]
    .filter((x) => x !== null)
    .join('\n')
}

export const enlaceWhatsapp = (telefono, texto) =>
  `https://wa.me/${telefono}?text=${encodeURIComponent(texto)}`

export const enlaceCorreo = (correo, asunto, texto) =>
  `mailto:${correo}?subject=${encodeURIComponent(asunto)}&body=${encodeURIComponent(texto)}`
