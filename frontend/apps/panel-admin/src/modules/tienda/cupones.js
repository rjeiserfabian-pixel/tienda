// Lógica pura de la pantalla «Cupones» de la tienda: estados, valores y validaciones.
import { aCampoFecha, desdeCampoFecha } from './ofertas'

export const ESTADOS_CUPON = {
  VIGENTE: { texto: 'Vigente', tono: 'verde' },
  PROGRAMADO: { texto: 'Programado', tono: 'azul' },
  VENCIDO: { texto: 'Vencido', tono: 'gris' },
  PAUSADO: { texto: 'Pausado', tono: 'ambar' },
  AGOTADO: { texto: 'Agotado', tono: 'rojo' },
}

export const FILTROS_ESTADO = [
  { valor: '', texto: 'Todos' },
  { valor: 'VIGENTE', texto: 'Vigentes' },
  { valor: 'PROGRAMADO', texto: 'Programados' },
  { valor: 'VENCIDO', texto: 'Vencidos' },
  { valor: 'PAUSADO', texto: 'Pausados' },
  { valor: 'AGOTADO', texto: 'Agotados' },
]

export const TIPOS = {
  PORCENTAJE: { texto: 'Porcentaje', detalle: 'Un % de descuento sobre los productos (ej. 10 %).', unidad: '%' },
  MONTO: { texto: 'Monto fijo', detalle: 'Un monto en soles menos en la compra (ej. S/ 20).', unidad: 'S/' },
  ENVIO_GRATIS: { texto: 'Envío gratis', detalle: 'El envío a domicilio no se cobra.', unidad: '' },
}

export const ALCANCES = {
  TODO: 'Toda la tienda',
  CATEGORIAS: 'Solo ciertas categorías',
  MARCAS: 'Solo ciertas marcas',
  PRODUCTOS: 'Solo ciertos productos',
}

/** Un texto corto de lo que hace el cupón (para la lista). */
export function resumenDeCupon(c) {
  if (c.tipo === 'PORCENTAJE') return `${Number(c.valor)} % de descuento${c.tope_descuento ? ` (máx. S/ ${Number(c.tope_descuento).toFixed(2)})` : ''}`
  if (c.tipo === 'MONTO') return `S/ ${Number(c.valor).toFixed(2)} de descuento`
  return 'Envío gratis'
}

export const cuponVacio = () => ({
  id: null,
  codigo: '',
  nombre: '',
  tipo: 'PORCENTAJE',
  valor: '10',
  tope_descuento: '',
  compra_minima: '0',
  inicia_en: '',
  termina_en: '',
  usos_maximos: '',
  usos_por_cliente: '1',
  alcance: 'TODO',
  categorias: [],
  marcas: [],
  productos: [], // { id, codigo, nombre }
  solo_primera_compra: false,
  incluye_ofertas: false,
  activo: true,
})

export const cuponDesdeServidor = (c) => ({
  id: c.id,
  codigo: c.codigo,
  nombre: c.nombre ?? '',
  tipo: c.tipo,
  valor: String(Number(c.valor)),
  tope_descuento: c.tope_descuento ? String(Number(c.tope_descuento)) : '',
  compra_minima: String(Number(c.compra_minima ?? 0)),
  inicia_en: aCampoFecha(c.inicia_en),
  termina_en: aCampoFecha(c.termina_en),
  usos_maximos: c.usos_maximos ? String(c.usos_maximos) : '',
  usos_por_cliente: String(c.usos_por_cliente ?? 1),
  alcance: c.alcance,
  categorias: (c.categorias ?? []).map((x) => x.id),
  marcas: (c.marcas ?? []).map((x) => x.id),
  productos: c.productos ?? [],
  solo_primera_compra: Boolean(c.solo_primera_compra),
  incluye_ofertas: Boolean(c.incluye_ofertas),
  activo: Boolean(c.activo),
})

const norm = (t) => String(t ?? '').trim()

/** Un código fácil de leer y de dictar (sin 0/O ni 1/I). */
export function codigoAlAzar(largo = 8) {
  const letras = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
  const bytes = new Uint32Array(largo)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => letras[b % letras.length]).join('')
}

/** Errores que se pueden ver sin llamar al servidor. */
export function revisarCupon(f) {
  const e = {}
  const codigo = norm(f.codigo).toUpperCase().replace(/\s/g, '')
  if (!/^[A-Z0-9_-]{3,30}$/.test(codigo)) e.codigo = 'Usa de 3 a 30 letras, números, guion o guion bajo.'
  const valor = Number(f.valor)
  if (f.tipo === 'PORCENTAJE' && !(valor > 0 && valor <= 100)) e.valor = 'El porcentaje va de 1 a 100.'
  if (f.tipo === 'MONTO' && !(valor > 0)) e.valor = 'Escribe el monto del descuento.'
  if (f.tipo === 'PORCENTAJE' && norm(f.tope_descuento) && !(Number(f.tope_descuento) > 0)) e.tope_descuento = 'El máximo debe ser mayor que cero.'
  if (!(Number(f.compra_minima) >= 0)) e.compra_minima = 'No puede ser negativa.'
  if (norm(f.usos_maximos) && !(Number.isInteger(Number(f.usos_maximos)) && Number(f.usos_maximos) >= 1)) e.usos_maximos = 'Un número entero desde 1, o déjalo vacío.'
  const porCliente = Number(f.usos_por_cliente)
  if (!(Number.isInteger(porCliente) && porCliente >= 1 && porCliente <= 100)) e.usos_por_cliente = 'Un número entre 1 y 100.'
  if (f.inicia_en && f.termina_en && new Date(f.termina_en) <= new Date(f.inicia_en)) e.termina_en = 'Debe terminar después de empezar.'
  if (f.alcance === 'CATEGORIAS' && f.categorias.length === 0) e.alcance = 'Elige al menos una categoría.'
  if (f.alcance === 'MARCAS' && f.marcas.length === 0) e.alcance = 'Elige al menos una marca.'
  if (f.alcance === 'PRODUCTOS' && f.productos.length === 0) e.alcance = 'Elige al menos un producto.'
  return e
}

/** El cuerpo que espera el servidor. */
export const cuerpoDeCupon = (f) => ({
  codigo: norm(f.codigo).toUpperCase().replace(/\s/g, ''),
  nombre: norm(f.nombre),
  tipo: f.tipo,
  valor: f.tipo === 'ENVIO_GRATIS' ? '0' : norm(f.valor),
  tope_descuento: f.tipo === 'PORCENTAJE' && norm(f.tope_descuento) ? norm(f.tope_descuento) : null,
  compra_minima: norm(f.compra_minima) || '0',
  inicia_en: desdeCampoFecha(f.inicia_en),
  termina_en: desdeCampoFecha(f.termina_en),
  usos_maximos: norm(f.usos_maximos) ? Number(f.usos_maximos) : null,
  usos_por_cliente: Number(f.usos_por_cliente),
  alcance: f.alcance,
  categorias: f.alcance === 'CATEGORIAS' ? f.categorias : [],
  marcas: f.alcance === 'MARCAS' ? f.marcas : [],
  productos: f.alcance === 'PRODUCTOS' ? f.productos.map((p) => p.id) : [],
  solo_primera_compra: f.solo_primera_compra,
  incluye_ofertas: f.incluye_ofertas,
  activo: f.activo,
})
