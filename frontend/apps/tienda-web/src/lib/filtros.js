/**
 * Los filtros del listado viajan en la dirección (`?marca=lenovo&esp.memoria-ram=16&orden=precio_asc`):
 * así la página se arma en el servidor, se puede compartir y funciona con el botón «atrás».
 */

export const ORDENES = [
  { valor: 'relevancia', texto: 'Más relevantes' },
  { valor: 'precio_asc', texto: 'Precio: de menor a mayor' },
  { valor: 'precio_desc', texto: 'Precio: de mayor a menor' },
  { valor: 'nuevos', texto: 'Más nuevos' },
  { valor: 'nombre', texto: 'Nombre (A-Z)' },
  { valor: 'descuento', texto: 'Mayor descuento' },
]

const ORDENES_VALIDOS = new Set(ORDENES.map((o) => o.valor))

const lista = (v) => (Array.isArray(v) ? v : v === undefined ? [] : [v])

/** Lee los filtros de `searchParams` (Next) a un objeto ordenado y validado. */
export function leerFiltros(searchParams = {}) {
  const esp = {}
  for (const [clave, valor] of Object.entries(searchParams)) {
    if (clave.startsWith('esp.')) {
      const valores = lista(valor).filter(Boolean)
      if (valores.length) esp[clave.slice(4)] = valores
    }
  }
  const orden = lista(searchParams.orden)[0]
  const pagina = Number.parseInt(lista(searchParams.page)[0], 10)
  return {
    q: (lista(searchParams.q)[0] ?? '').trim().slice(0, 80),
    marca: lista(searchParams.marca).filter(Boolean),
    precio_min: lista(searchParams.precio_min)[0] ?? '',
    precio_max: lista(searchParams.precio_max)[0] ?? '',
    disponible: lista(searchParams.disponible)[0] === '1',
    nuevo: lista(searchParams.nuevo)[0] === '1',
    destacado: lista(searchParams.destacado)[0] === '1',
    orden: ORDENES_VALIDOS.has(orden) ? orden : 'relevancia',
    page: Number.isFinite(pagina) && pagina > 0 ? pagina : 1,
    esp,
  }
}

/** Los filtros como parámetros para la API (agrega la categoría o familia de la página). */
export function parametrosApi(filtros, extra = {}) {
  const params = {
    ...extra,
    q: filtros.q || undefined,
    marca: filtros.marca,
    precio_min: filtros.precio_min || undefined,
    precio_max: filtros.precio_max || undefined,
    disponible: filtros.disponible ? '1' : undefined,
    nuevo: filtros.nuevo ? '1' : undefined,
    destacado: filtros.destacado ? '1' : undefined,
    orden: filtros.orden !== 'relevancia' ? filtros.orden : undefined,
    page: filtros.page > 1 ? filtros.page : undefined,
  }
  for (const [clave, valores] of Object.entries(filtros.esp)) params[`esp.${clave}`] = valores
  return params
}

/** Dirección con los filtros aplicados (sin los vacíos). `cambios` pisa lo que ya había. */
export function enlaceConFiltros(ruta, filtros, cambios = {}) {
  const f = { ...filtros, ...cambios }
  if (!('page' in cambios)) f.page = 1 // cambiar un filtro vuelve a la primera página
  const partes = new URLSearchParams()
  const poner = (clave, valor) => {
    if (valor !== undefined && valor !== null && valor !== '') partes.append(clave, String(valor))
  }
  poner('q', f.q)
  f.marca.forEach((m) => poner('marca', m))
  poner('precio_min', f.precio_min)
  poner('precio_max', f.precio_max)
  if (f.disponible) poner('disponible', '1')
  if (f.nuevo) poner('nuevo', '1')
  if (f.destacado) poner('destacado', '1')
  if (f.orden !== 'relevancia') poner('orden', f.orden)
  for (const [clave, valores] of Object.entries(f.esp)) valores.forEach((v) => poner(`esp.${clave}`, v))
  if (f.page > 1) poner('page', f.page)
  const texto = partes.toString()
  return texto ? `${ruta}?${texto}` : ruta
}

/** ¿Hay algún filtro aplicado (sin contar el orden ni la página)? */
export function hayFiltros(filtros) {
  return Boolean(
    filtros.q ||
      filtros.marca.length ||
      filtros.precio_min ||
      filtros.precio_max ||
      filtros.disponible ||
      filtros.nuevo ||
      filtros.destacado ||
      Object.keys(filtros.esp).length,
  )
}
