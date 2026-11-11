// Datos y reglas de la toma de inventario físico (los textos y colores de cada estado, y la
// validación de la cantidad contada, que es la misma que hace el servidor).
import { paraServidor } from './inventario'

export const ESTADOS_TOMA = {
  BORRADOR: { texto: 'Borrador', tono: 'gris' },
  ABIERTA: { texto: 'Abierta', tono: 'azul' },
  EN_CONTEO: { texto: 'En conteo', tono: 'ambar' },
  EN_RECONTEO: { texto: 'En reconteo', tono: 'naranja' },
  CERRADA: { texto: 'Cerrada', tono: 'morado' },
  APROBADA: { texto: 'Aprobada', tono: 'verde' },
  ANULADA: { texto: 'Anulada', tono: 'rojo' },
}

export const ESTADOS_FISICOS = {
  BUENO: 'Bueno',
  DEFECTUOSO: 'Defectuoso',
  GARANTIA: 'En garantía',
  DE_TERCEROS: 'De terceros',
}

export const TURNOS = {
  MANANA: 'Mañana',
  TARDE: 'Tarde',
  MANANA_Y_TARDE: 'Mañana y tarde',
}

/** Estados en los que se puede contar. */
export const ESTADOS_DE_CONTEO = ['ABIERTA', 'EN_CONTEO', 'EN_RECONTEO']
export const puedeContarEn = (estado) => ESTADOS_DE_CONTEO.includes(estado)

/** «N° 000012», como se ve en los demás documentos del almacén. */
export const numeroToma = (numero) => `N° ${String(numero).padStart(6, '0')}`

/** Fecha y hora del servidor (ISO con zona) → «16/10/2026, 10:15». */
export const fechaHora = (iso) => {
  if (!iso) return '—'
  const fecha = new Date(iso)
  return Number.isNaN(fecha.getTime())
    ? '—'
    : fecha.toLocaleString('es-PE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

/** Hora local actual, «HH:MM», para los turnos. */
export const horaActual = () => new Date().toTimeString().slice(0, 5)

const FORMATO_SOLES = new Intl.NumberFormat('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** Soles del servidor (texto) con signo: «S/ 1,250.00», «−S/ 20.00». */
export const soles = (valor) => {
  const n = Number(valor)
  if (valor === null || valor === undefined || valor === '' || !Number.isFinite(n)) return '—'
  return `${n < 0 ? '−' : ''}S/ ${FORMATO_SOLES.format(Math.abs(n))}`
}

const TOPE = 99999999999.999

/**
 * Revisa la cantidad escrita antes de enviarla. Devuelve el mensaje del problema, o '' si está bien.
 * Misma regla del servidor: no negativa, hasta 3 decimales y, si la unidad se cuenta por pieza
 * (o el producto lleva serie), solo enteros.
 */
export function revisarCantidad(texto, admiteDecimales) {
  const t = paraServidor(texto)
  if (t === '') return 'Escriba la cantidad.'
  if (!/^\d+(\.\d{1,3})?$/.test(t)) return 'Solo números, con hasta 3 decimales.'
  if (!admiteDecimales && t.includes('.')) return 'Esta unidad se cuenta en números enteros.'
  if (Number(t) > TOPE) return 'La cantidad es demasiado grande.'
  return ''
}
