// Datos y formatos del inventario (stock, movimientos y Kardex).

export const TIPOS_MOVIMIENTO = {
  ENTRADA: { texto: 'Entrada', tono: 'verde' },
  SALIDA: { texto: 'Salida', tono: 'ambar' },
}

export const ORIGENES = {
  COMPRA: 'Compra',
  VENTA: 'Venta',
  DEVOLUCION_CLIENTE: 'Devolución de un cliente',
  DEVOLUCION_PROVEEDOR: 'Devolución a un proveedor',
  SALDO_INICIAL: 'Saldo inicial',
  AJUSTE: 'Ajuste de inventario',
  TRASPASO: 'Traspaso entre almacenes',
  SERVICIO_TECNICO: 'Repuestos usados en un servicio técnico',
  VENTA_INTERNA: 'Venta interna entre empresas',
  TRASLADO_EMPRESAS: 'Traslado entre empresas',
  MERMA: 'Merma o desmedro',
  EXTORNO: 'Extorno por anulación',
}

/** Lo que una persona puede registrar a mano, según sea entrada o salida. */
export const ORIGENES_MANUALES = {
  ENTRADA: ['COMPRA', 'DEVOLUCION_CLIENTE', 'SALDO_INICIAL', 'AJUSTE'],
  SALIDA: ['AJUSTE', 'MERMA'], // la devolución a un proveedor se hace desde la compra (Compras)
}

/** Movimientos que llevan comprobante, proveedor o cliente (los internos no). */
export const CON_COMPROBANTE = ['COMPRA', 'DEVOLUCION_CLIENTE']
export const CON_PROVEEDOR = ['COMPRA']
export const CON_CLIENTE = ['DEVOLUCION_CLIENTE']

const FORMATO_CANTIDAD = new Intl.NumberFormat('es-PE', { maximumFractionDigits: 3 })
const FORMATO_UNITARIO = new Intl.NumberFormat('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 4 })

/** Cantidades del servidor (texto) con hasta 3 decimales: «10», «2,5». */
export const cantidad = (valor) => {
  const n = Number(valor)
  return valor === null || valor === undefined || valor === '' || !Number.isFinite(n) ? '—' : FORMATO_CANTIDAD.format(n)
}

/** Costo unitario con hasta 4 decimales: «S/ 20,6667». */
export const solesUnitario = (valor) => {
  const n = Number(valor)
  return valor === null || valor === undefined || valor === '' || !Number.isFinite(n) ? '—' : `S/ ${FORMATO_UNITARIO.format(n)}`
}

/** Fecha AAAA-MM-DD del servidor → 28/10/2026 (sin pasar por zonas horarias). */
export const fechaCorta = (iso) => {
  if (!iso) return '—'
  const [a, m, d] = String(iso).slice(0, 10).split('-')
  return a && m && d ? `${d}/${m}/${a}` : '—'
}

/** Hoy en AAAA-MM-DD, en la hora local del navegador. */
export const hoyIso = () => new Date().toLocaleDateString('en-CA')

/** Periodo AAAAMM → 10/2026. */
export const etiquetaPeriodo = (periodo) => (periodo ? `${periodo.slice(4)}/${periodo.slice(0, 4)}` : '—')

/** Texto escrito por una persona («2,5») → texto que entiende el servidor («2.5»). */
export const paraServidor = (texto) => String(texto ?? '').trim().replace(',', '.')

let contadorDeLineas = 0
/** Línea vacía del formulario de movimientos (el `id` es solo para las claves de React). */
export const nuevaLinea = () => ({ id: ++contadorDeLineas, producto: null, cantidad: '', precio: '', series: [], ubicacion: '' })

/** Series o IMEI escritos o pegados (uno por línea, o separados por coma o espacio) → lista limpia. */
export const parsearSeries = (texto) =>
  String(texto ?? '')
    .split(/[\s,;]+/)
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean)

/** Una serie como la guarda el servidor: sin espacios de más y en mayúsculas. */
export const normalizarSerie = (texto) => String(texto ?? '').trim().replace(/\s+/g, ' ').toUpperCase()

/** Los números de una lista de series (`[{ numero, otros_datos }]`). */
export const numerosDe = (series) => (series ?? []).map((s) => s.numero)

/** Misma regla que el servidor: de 3 a 40 letras, números, guiones o puntos. */
export const serieValida = (serie) => /^[A-Z0-9][A-Z0-9\-_./]{2,39}$/.test(serie)
