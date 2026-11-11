// Cálculo de precios de los productos. Misma regla que el servidor. El precio es lo que manda;
// la utilidad o el margen se derivan de él y del costo.

/** Texto del formulario → número, o `null` si está vacío o no es un número. */
export const aNumero = (texto) => {
  if (texto === '' || texto === null || texto === undefined) return null
  const n = Number(String(texto).replace(',', '.'))
  return Number.isFinite(n) ? n : null
}

const redondear = (n, decimales) => String(Number(n.toFixed(decimales)))

/**
 * Cómo piensa la ganancia cada organización (se elige en Organización):
 * - UTILIDAD, sobre el costo:  precio = costo × (1 + utilidad / 100)
 * - MARGEN, sobre el precio:   precio = costo ÷ (1 − margen / 100)
 * El precio es lo que se guarda; el porcentaje solo es una forma de escribirlo y de verlo.
 */
export const MODOS_PRECIO = {
  UTILIDAD: { nombre: 'Utilidad', articulo: 'la utilidad', encabezado: '% Utilidad', explicacion: 'sobre el costo' },
  MARGEN: { nombre: 'Margen', articulo: 'el margen', encabezado: '% Margen', explicacion: 'sobre el precio de venta' },
}

export const precioDesdePorcentaje = (costo, porcentaje, modo = 'UTILIDAD') => {
  const c = aNumero(costo)
  const p = aNumero(porcentaje)
  if (c === null || c <= 0 || p === null) return ''
  if (modo === 'MARGEN') return p >= 100 ? '' : redondear(c / (1 - p / 100), 2)
  return redondear(c * (1 + p / 100), 2)
}

export const porcentajeDesdePrecio = (costo, precio, modo = 'UTILIDAD') => {
  const c = aNumero(costo)
  const p = aNumero(precio)
  if (c === null || c <= 0 || p === null) return ''
  if (modo === 'MARGEN') return p <= 0 ? '' : redondear((1 - c / p) * 100, 2)
  return redondear((p / c - 1) * 100, 2)
}

export const soles = (valor) => {
  const n = aNumero(valor)
  return n === null ? '—' : `S/ ${n.toLocaleString('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export const TIPOS_PRODUCTO = [
  ['BIEN', 'Bien (se almacena y se vende)'],
  ['SERVICIO', 'Servicio (sin stock)'],
]

/** Foto máxima y formatos que acepta el servidor (se revisa antes de subir). */
export const FOTO_MAX_BYTES = 5 * 1024 * 1024
export const FOTO_FORMATOS = ['image/jpeg', 'image/png', 'image/webp']
export const FOTOS_MAX = 8
