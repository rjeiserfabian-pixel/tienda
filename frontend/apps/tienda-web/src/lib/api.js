/**
 * Cliente de la API pública de la tienda (solo servidor).
 *
 * Todas las consultas se guardan un minuto en la caché de datos de Next (igual que la de la API),
 * llevan un tope de espera y, si la API no responde, lanzan un `ErrorApi` con un mensaje claro en vez
 * de dejar la página colgada.
 */
const API_URL = process.env.API_URL || 'http://localhost:8000'
const ESPERA_MS = 8000
export const SEGUNDOS_CACHE = 60

export class ErrorApi extends Error {
  constructor(estado, codigo, mensaje) {
    super(mensaje)
    this.name = 'ErrorApi'
    this.estado = estado
    this.codigo = codigo
  }

  get noEncontrado() {
    return this.estado === 404
  }

  get tiendaCerrada() {
    return this.estado === 503
  }
}

function direccion(ruta, params) {
  const url = new URL(`/api/v1/tienda/${ruta}`, API_URL)
  for (const [clave, valor] of Object.entries(params ?? {})) {
    for (const v of Array.isArray(valor) ? valor : [valor]) {
      if (v !== undefined && v !== null && v !== '') url.searchParams.append(clave, String(v))
    }
  }
  return url
}

/** Consulta una ruta de la API pública y devuelve su JSON. */
export async function consultar(ruta, params, { segundos = SEGUNDOS_CACHE } = {}) {
  let respuesta
  try {
    respuesta = await fetch(direccion(ruta, params), {
      headers: { Accept: 'application/json' },
      next: { revalidate: segundos, tags: ['tienda'] },
      signal: AbortSignal.timeout(ESPERA_MS),
    })
  } catch {
    throw new ErrorApi(0, 'sin_conexion', 'No pudimos conectar con la tienda. Intenta de nuevo en un momento.')
  }
  if (!respuesta.ok) {
    let codigo = 'error'
    try {
      codigo = (await respuesta.json())?.error?.codigo ?? codigo
    } catch {
      // la respuesta no era JSON: se usa el código genérico
    }
    throw new ErrorApi(respuesta.status, codigo, `La tienda respondió ${respuesta.status}.`)
  }
  return sinBarraFinal(await respuesta.json())
}

const FOTO = /^\/api\/v1\/tienda\/fotos\/\d+\/(mini|grande)\/$/

/**
 * Las fotos llegan con barra final (así las sirve la API), pero Next redirige toda dirección con
 * barra final a la versión sin ella: cada foto costaría una vuelta de más. Aquí las dejamos sin la
 * barra; la regla de reenvío de next.config.mjs la vuelve a poner al llegar a la API.
 */
function sinBarraFinal(valor) {
  if (typeof valor === 'string') return FOTO.test(valor) ? valor.slice(0, -1) : valor
  if (Array.isArray(valor)) return valor.map(sinBarraFinal)
  if (valor && typeof valor === 'object') {
    return Object.fromEntries(Object.entries(valor).map(([k, v]) => [k, sinBarraFinal(v)]))
  }
  return valor
}

export const obtenerMenu = () => consultar('menu/', undefined, { segundos: 300 })
export const obtenerInicio = () => consultar('inicio/')
export const obtenerProductos = (params) => consultar('productos/', params)
export const obtenerProducto = (slug) => consultar(`productos/${encodeURIComponent(slug)}/`)
export const obtenerConfiguracion = () => consultar('configuracion/', undefined, { segundos: 120 })
export const obtenerBanners = () => consultar('banners/', undefined, { segundos: 60 })
export const obtenerMapaDelSitio = () => consultar('sitemap/', undefined, { segundos: 300 })

/** Igual que `consultar`, pero devuelve `null` si no existe (404) en lugar de lanzar el error. */
export async function consultarOpcional(funcion, ...args) {
  try {
    return await funcion(...args)
  } catch (error) {
    if (error instanceof ErrorApi && error.noEncontrado) return null
    throw error
  }
}
