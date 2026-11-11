import { ErrorApi, obtenerProductos } from '@/lib/api'
import { parametrosApi } from '@/lib/filtros'

/**
 * Pide el listado a la API. `extra` son los parámetros propios de la página (categoria, familia…).
 * Devuelve `null` si la API dice que esa categoría, familia o marca no existe (404), para que la
 * página responda `notFound()`. Pide siempre las facetas: alimentan los filtros del costado.
 */
export async function cargarListado(filtros, extra = {}) {
  try {
    return await obtenerProductos(parametrosApi(filtros, { ...extra, facetas: '1' }))
  } catch (error) {
    if (error instanceof ErrorApi && error.noEncontrado) return null
    throw error
  }
}

/** Números de página a mostrar: 1 … 4 5 [6] 7 8 … 20 (con `null` donde van los puntos suspensivos). */
export function rangoDePaginas(actual, total, alrededor = 1) {
  const paginas = new Set([1, total])
  for (let p = actual - alrededor; p <= actual + alrededor; p += 1) {
    if (p >= 1 && p <= total) paginas.add(p)
  }
  const orden = [...paginas].sort((a, b) => a - b)
  const salida = []
  orden.forEach((p, i) => {
    if (i > 0 && p - orden[i - 1] > 1) salida.push(null)
    salida.push(p)
  })
  return salida
}

/** «1 producto» / «24 productos». */
export const textoCantidad = (n) => `${n.toLocaleString('es-PE')} ${n === 1 ? 'producto' : 'productos'}`

/** Etiqueta legible de un valor de especificación (busca la etiqueta que trae la API). */
export function etiquetaDeEspecificacion(facetas, clave, valor) {
  const campo = facetas?.especificaciones?.find((e) => e.clave === clave)
  const opcion = campo?.opciones.find((o) => o.valor === valor)
  return { campo: campo?.nombre ?? clave, texto: opcion?.etiqueta ?? valor }
}

/**
 * Metadatos de una página de listado. Con filtros o desde la página 2 no se indexa (son miles de
 * combinaciones repetidas); la página base sí, y apunta a sí misma como dirección canónica.
 */
export function metadatosDeListado({ ruta, titulo, descripcion, filtros, indexable = true }) {
  const filtrada = Boolean(
    filtros.q ||
      filtros.marca.length ||
      filtros.precio_min ||
      filtros.precio_max ||
      filtros.disponible ||
      filtros.nuevo ||
      filtros.destacado ||
      Object.keys(filtros.esp).length ||
      filtros.orden !== 'relevancia',
  )
  const canonica = filtros.page > 1 && !filtrada ? `${ruta}?page=${filtros.page}` : ruta
  return {
    title: filtros.page > 1 ? `${titulo} - Página ${filtros.page}` : titulo,
    description: descripcion,
    alternates: { canonical: canonica },
    robots: { index: indexable && !filtrada && filtros.page === 1, follow: true },
  }
}
