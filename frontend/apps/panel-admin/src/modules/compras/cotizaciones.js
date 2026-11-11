// Lógica pura de las pantallas de cotizaciones de compra: estados, borrador, cuerpo que recibe el
// servidor, validaciones, elección de ganadores y texto para el proveedor. Los totales y el mejor
// precio los calcula SIEMPRE el servidor (comparativo); aquí solo se arman y se revisan datos.
import { hoyIso, paraServidor } from '../almacen/inventario'
import { aNumero } from '../almacen/utilidades'
import { lineaDeProducto, MONEDAS } from './compras'
import { enlaceCorreo, enlaceWhatsapp, telefonoWhatsapp } from './ordenes'

export { enlaceCorreo, enlaceWhatsapp, telefonoWhatsapp }

export const MAX_PROVEEDORES = 15
export const MAX_BYTES_EXCEL = 2 * 1024 * 1024

/** Cómo se llama y se pinta cada estado de una cotización. */
export const ESTADOS_COTIZACION = {
  BORRADOR: { texto: 'Borrador', tono: 'gris' },
  ABIERTA: { texto: 'Abierta', tono: 'azul' },
  ADJUDICADA: { texto: 'Adjudicada', tono: 'verde' },
  ANULADA: { texto: 'Anulada', tono: 'rojo' },
}

/** Cómo se llama y se pinta lo que contestó cada proveedor. */
export const ESTADOS_RESPUESTA = {
  PENDIENTE: { texto: 'Sin responder', tono: 'ambar' },
  RESPONDIDA: { texto: 'Respondida', tono: 'verde' },
  DECLINADA: { texto: 'No cotiza', tono: 'gris' },
}

export const ORIGENES_RESPUESTA = { MANUAL: 'Registrada a mano', ARCHIVO: 'Importada de Excel' }

/** Qué acciones admite una cotización según su estado (los permisos se revisan aparte). */
export const accionesDe = (estado) => ({
  responder: estado === 'BORRADOR' || estado === 'ABIERTA',
  adjudicar: estado === 'ABIERTA',
  anular: estado === 'BORRADOR' || estado === 'ABIERTA',
  editar: estado === 'BORRADOR',
})

export const borradorCotizacion = () => ({
  almacen: '',
  fecha: hoyIso(),
  fechaLimite: '',
  moneda: 'PEN',
  incluyeIgv: false,
  observacion: '',
  proveedores: [],
  lineas: [],
})

const CANTIDAD = /^\d+([.,]\d{1,3})?$/
const PRECIO = /^\d+([.,]\d{1,6})?$/

/** Cuerpo que recibe el servidor para crear o editar. */
export function armarCuerpoCotizacion(b, { empresa, almacen }) {
  return {
    ...(empresa ? { empresa } : {}),
    almacen: Number(almacen) || null,
    fecha: b.fecha,
    ...(b.fechaLimite ? { fecha_limite: b.fechaLimite } : {}),
    moneda: b.moneda,
    precios_incluyen_igv: b.incluyeIgv,
    observacion: b.observacion.trim(),
    proveedores: b.proveedores.map((p) => p.id),
    lineas: b.lineas.map((l) => ({
      producto: l.producto.id,
      ...(l.presentacion ? { presentacion: Number(l.presentacion) } : {}),
      cantidad: paraServidor(l.cantidad),
    })),
  }
}

/** Revisa el borrador. `faltan` es lo que impide guardar, en palabras. */
export function validarCotizacion(b, almacen) {
  const campos = {}
  const porLinea = {}
  const faltan = []
  const falta = (clave, texto, mensaje) => {
    campos[clave] = mensaje ?? texto
    faltan.push(texto)
  }
  if (!almacen) falta('almacen', 'Elegir el almacén', 'Elija el almacén.')
  if (!b.fecha) falta('fecha', 'Indicar la fecha', 'Indique la fecha.')
  else if (b.fecha > hoyIso()) falta('fecha', 'Corregir la fecha (es futura)', 'La fecha no puede ser futura.')
  if (b.fechaLimite && b.fecha && b.fechaLimite < b.fecha) falta('fechaLimite', 'Corregir la fecha límite', 'No puede ser anterior a la fecha.')
  if (b.lineas.length === 0) faltan.push('Agregar al menos un producto')
  if (b.proveedores.length > MAX_PROVEEDORES) falta('proveedores', `Dejar hasta ${MAX_PROVEEDORES} proveedores`, `Hasta ${MAX_PROVEEDORES} proveedores.`)
  const vistas = new Set()
  let malas = 0
  for (const l of b.lineas) {
    const e = {}
    const cantidad = aNumero(l.cantidad)
    if (cantidad === null || cantidad <= 0) e.cantidad = 'Mayor que cero.'
    else if (!CANTIDAD.test(String(l.cantidad).trim())) e.cantidad = 'Hasta 3 decimales.'
    const clave = `${l.producto.id}-${l.presentacion || 0}`
    if (vistas.has(clave)) e.cantidad = 'Producto repetido: súmalo en una línea.'
    vistas.add(clave)
    if (Object.keys(e).length) {
      porLinea[l.id] = e
      malas += 1
    }
  }
  if (malas) faltan.push(`Corregir la cantidad de ${malas === 1 ? 'un producto' : `${malas} productos`}`)
  return { campos, porLinea, faltan, valido: faltan.length === 0 && Object.keys(campos).length === 0 }
}

/** Del detalle de una cotización al borrador de la pantalla (para editarla). `productos` por id. */
export function borradorDesdeCotizacion(c, productos, proveedores) {
  return {
    almacen: String(c.almacen),
    fecha: c.fecha,
    fechaLimite: c.fecha_limite ?? '',
    moneda: c.moneda,
    incluyeIgv: c.precios_incluyen_igv,
    observacion: c.observacion ?? '',
    proveedores: c.proveedores.map((p) => proveedores[p.proveedor]).filter(Boolean),
    lineas: c.lineas
      .filter((l) => productos[l.producto])
      .map((l) => ({
        ...lineaDeProducto(productos[l.producto]),
        presentacion: l.presentacion ? String(l.presentacion) : '',
        cantidad: String(Number(l.cantidad)),
      })),
  }
}

/** ¿Se puede editar? Solo en borrador y mientras ningún proveedor haya dado precios. */
export const sePuedeEditar = (c) => c.estado === 'BORRADOR' && !c.proveedores.some((p) => p.estado === 'RESPONDIDA')

// ---------- Precios y textos ----------
const FORMATO_PRECIO = new Intl.NumberFormat('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 6 })

/** Precio unitario con hasta 6 decimales y su símbolo: «S/ 10,50». */
export const precioUnitario = (valor, moneda = 'PEN') => {
  const n = aNumero(valor)
  return n === null ? '—' : `${MONEDAS[moneda]?.simbolo ?? 'S/'} ${FORMATO_PRECIO.format(n)}`
}

/** Texto de la solicitud para el proveedor: productos y cantidades, SIN precios. */
export function textoCotizacion(c, { fechaCorta, cantidad }) {
  const emisor = c.emisor?.nombre ?? ''
  const lineas = (c.lineas ?? []).map((l) => `• ${cantidad(l.cantidad)} ${l.unidad ?? ''} ${l.producto_nombre}`.replace(/\s+/g, ' ')).join('\n')
  const base = c.precios_incluyen_igv ? 'con IGV incluido' : 'sin IGV'
  return [
    `Solicitud de cotización ${c.codigo}${emisor ? ` - ${emisor}` : ''}`,
    `Fecha: ${fechaCorta(c.fecha)}`,
    c.fecha_limite ? `Responder hasta: ${fechaCorta(c.fecha_limite)}` : null,
    '',
    'Necesitamos precio de:',
    lineas,
    '',
    `Por favor cotizar en ${MONEDAS[c.moneda]?.nombre?.toLowerCase() ?? 'soles'}, precios ${base}, indicando forma de pago, plazo de entrega y validez de la oferta.`,
    c.observacion ? `Nota: ${c.observacion}` : null,
    'Gracias.',
  ]
    .filter((x) => x !== null)
    .join('\n')
}

// ---------- Respuesta a mano ----------
/** Formulario de la respuesta de un proveedor, precargado con lo que ya contestó (si contestó). */
export function borradorRespuesta(c, respuestaId) {
  const prov = c.comparativo.proveedores.find((p) => p.respuesta === respuestaId)
  const texto = (v) => (v === null || v === undefined ? '' : String(Number(v)))
  return {
    formaPago: prov?.forma_pago || 'CONTADO',
    plazoDias: prov?.plazo_dias ? String(prov.plazo_dias) : '30',
    plazoEntrega: prov?.plazo_entrega_dias ? String(prov.plazo_entrega_dias) : '',
    validezHasta: prov?.validez_hasta ?? '',
    observacion: prov?.observacion ?? '',
    filas: c.comparativo.lineas.map((l) => {
      const oferta = l.ofertas.find((o) => o.respuesta === respuestaId)
      return {
        linea: l.linea,
        precio: texto(oferta?.precio_unitario),
        ofrecida: texto(oferta?.cantidad_ofrecida),
        observacion: oferta?.observacion ?? '',
      }
    }),
  }
}

/** Revisa la respuesta escrita a mano. */
export function validarRespuesta(r, lineas, fechaCotizacion) {
  const campos = {}
  const porFila = {}
  if (r.formaPago === 'CREDITO') {
    const plazo = Number(r.plazoDias)
    if (!Number.isInteger(plazo) || plazo < 1 || plazo > 365) campos.plazoDias = 'De 1 a 365 días.'
  }
  if (r.plazoEntrega !== '') {
    const entrega = Number(r.plazoEntrega)
    if (!Number.isInteger(entrega) || entrega < 0 || entrega > 365) campos.plazoEntrega = 'De 0 a 365 días.'
  }
  if (r.validezHasta && fechaCotizacion && r.validezHasta < fechaCotizacion) campos.validezHasta = 'No puede ser anterior a la cotización.'
  let conPrecio = 0
  r.filas.forEach((f, i) => {
    const e = {}
    if (f.precio.trim() !== '') {
      conPrecio += 1
      if (!PRECIO.test(f.precio.trim())) e.precio = 'Número con hasta 6 decimales.'
      if (f.ofrecida.trim() !== '') {
        const ofrecida = aNumero(f.ofrecida)
        const pedida = aNumero(lineas[i]?.cantidad)
        if (!CANTIDAD.test(f.ofrecida.trim()) || ofrecida === null || ofrecida <= 0) e.ofrecida = 'Mayor que cero, hasta 3 decimales.'
        else if (pedida !== null && ofrecida > pedida) e.ofrecida = 'No puede pasar de lo pedido.'
      }
    } else if (f.ofrecida.trim() !== '') {
      e.precio = 'Indique el precio.'
    }
    if (Object.keys(e).length) porFila[f.linea] = e
  })
  const faltan = []
  if (conPrecio === 0) faltan.push('Indique el precio de al menos un producto.')
  if (Object.keys(porFila).length) faltan.push('Corrija los precios o cantidades marcados.')
  if (Object.keys(campos).length) faltan.push('Corrija las condiciones marcadas.')
  return { campos, porFila, faltan, valido: faltan.length === 0 }
}

/** Cuerpo de la respuesta a mano. Solo viajan las filas con precio; el resto es «no cotiza». */
export function armarCuerpoRespuesta(r, respuestaId) {
  return {
    respuesta: respuestaId,
    forma_pago: r.formaPago,
    plazo_dias: r.formaPago === 'CREDITO' ? Number(r.plazoDias) : 0,
    plazo_entrega_dias: r.plazoEntrega === '' ? 0 : Number(r.plazoEntrega),
    ...(r.validezHasta ? { validez_hasta: r.validezHasta } : {}),
    observacion: r.observacion.trim(),
    precios: r.filas
      .filter((f) => f.precio.trim() !== '')
      .map((f) => ({
        linea: f.linea,
        precio_unitario: paraServidor(f.precio),
        ...(f.ofrecida.trim() !== '' ? { cantidad_ofrecida: paraServidor(f.ofrecida) } : {}),
        ...(f.observacion.trim() ? { observacion: f.observacion.trim() } : {}),
      })),
  }
}

// ---------- Elegir ganadores ----------
/** Cantidad máxima que puede darse de una oferta: lo que ofreció, o todo lo pedido. */
export const maximoDe = (linea, oferta) => aNumero(oferta?.cantidad_ofrecida) ?? aNumero(linea.cantidad) ?? 0

const ofertaDe = (linea, respuesta) => linea.ofertas.find((o) => String(o.respuesta) === String(respuesta) && o.precio_unitario !== null)

/** Un ganador propuesto por línea: el que dio el mejor precio (vacío si nadie cotizó). */
export function ganadoresIniciales(comparativo) {
  return Object.fromEntries(
    comparativo.lineas.map((l) => {
      const mejor = l.ofertas.find((o) => o.es_mejor)
      return [l.linea, { respuesta: mejor ? String(mejor.respuesta) : '', cantidad: mejor ? String(maximoDe(l, mejor)) : '' }]
    }),
  )
}

/** Revisa la elección: cada ganador debe haber cotizado ese producto y no pasar de lo que ofreció. */
export function validarGanadores(comparativo, elegidos) {
  const porLinea = {}
  let asignadas = 0
  const ordenes = new Set()
  let estimado = 0
  for (const l of comparativo.lineas) {
    const g = elegidos[l.linea]
    if (!g?.respuesta) continue
    const oferta = ofertaDe(l, g.respuesta)
    const cantidad = aNumero(g.cantidad)
    if (!oferta) porLinea[l.linea] = 'Ese proveedor no cotizó este producto.'
    else if (cantidad === null || cantidad <= 0) porLinea[l.linea] = 'Mayor que cero.'
    else if (!CANTIDAD.test(String(g.cantidad).trim())) porLinea[l.linea] = 'Hasta 3 decimales.'
    else if (cantidad > maximoDe(l, oferta)) porLinea[l.linea] = `No más de ${maximoDe(l, oferta)}.`
    else {
      asignadas += 1
      ordenes.add(g.respuesta)
      estimado += cantidad * Number(oferta.precio_unitario)
    }
  }
  const faltan = []
  if (asignadas === 0 && Object.keys(porLinea).length === 0) faltan.push('Elija el proveedor de al menos un producto.')
  if (Object.keys(porLinea).length) faltan.push('Corrija las cantidades marcadas.')
  return { porLinea, asignadas, ordenes: ordenes.size, estimado, faltan, valido: faltan.length === 0 && asignadas > 0 }
}

/** Cuerpo de la adjudicación: solo las líneas con ganador. */
export function armarCuerpoAdjudicacion(comparativo, elegidos) {
  return {
    asignaciones: comparativo.lineas
      .filter((l) => elegidos[l.linea]?.respuesta)
      .map((l) => ({
        linea: l.linea,
        respuesta: Number(elegidos[l.linea].respuesta),
        cantidad: paraServidor(elegidos[l.linea].cantidad),
      })),
  }
}
