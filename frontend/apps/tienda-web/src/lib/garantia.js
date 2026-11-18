/**
 * Consulta de garantías desde la tienda.
 *
 * La API pública (`/api/v1/garantias/publico/<código>/`) solo devuelve lo que el cliente puede ver:
 * producto, serie, fechas, si sigue vigente y cómo contactar a la tienda. Nunca precios ni datos
 * del cliente. El código del QR es la única llave: por eso estas consultas NUNCA se guardan en la
 * caché de Next y todo código se valida con el mismo formato estricto que la API.
 */
const API_URL = process.env.API_URL || 'http://localhost:8000'
const ESPERA_MS = 8000

/** Mismo formato que acepta la API: letras, números, guion y guion bajo, de 8 a 40 caracteres. */
export const FORMATO_TOKEN = /^[A-Za-z0-9_-]{8,40}$/
const LARGO_MAXIMO_ENTRADA = 300

/** Saca el código de lo que pegó el cliente: el código solo o el enlace del QR (`…/garantia/<código>`). */
export function extraerToken(entrada) {
  const texto = String(entrada ?? '').trim()
  if (!texto || texto.length > LARGO_MAXIMO_ENTRADA) return null
  if (FORMATO_TOKEN.test(texto)) return texto
  let url
  try {
    url = new URL(texto.includes('://') ? texto : `https://${texto}`)
  } catch {
    return null
  }
  if (url.protocol !== 'https:' && url.protocol !== 'http:') return null
  const trozos = url.pathname.split('/').filter(Boolean)
  const i = trozos.lastIndexOf('garantia')
  if (i >= 0 && trozos.length === i + 2) {
    let candidato
    try {
      candidato = decodeURIComponent(trozos[i + 1])
    } catch {
      return null
    }
    return FORMATO_TOKEN.test(candidato) ? candidato : null
  }
  return null
}

/** Consulta una garantía (solo servidor). Devuelve `{ situacion: 'ok' | 'no_encontrado' | 'limitado' | 'error', datos? }`. */
export async function obtenerGarantia(token) {
  if (!FORMATO_TOKEN.test(token ?? '')) return { situacion: 'no_encontrado' }
  const url = new URL(`/api/v1/garantias/publico/${encodeURIComponent(token)}/`, API_URL)
  let respuesta
  try {
    respuesta = await fetch(url, {
      headers: { Accept: 'application/json' },
      cache: 'no-store', // dato privado: ni caché de Next ni caché compartida
      redirect: 'manual',
      signal: AbortSignal.timeout(ESPERA_MS),
    })
  } catch {
    return { situacion: 'error' }
  }
  if (respuesta.status === 404) return { situacion: 'no_encontrado' }
  if (respuesta.status === 429) return { situacion: 'limitado' }
  if (!respuesta.ok) return { situacion: 'error' }
  try {
    return { situacion: 'ok', datos: await respuesta.json() }
  } catch {
    return { situacion: 'error' }
  }
}

const formato = (opciones) => (iso) => {
  if (!iso) return ''
  const fecha = new Date(`${String(iso).slice(0, 10)}T12:00:00`)
  return Number.isNaN(fecha.getTime()) ? '' : fecha.toLocaleDateString('es-PE', opciones)
}

export const fechaDia = formato({ day: 'numeric', month: 'long', year: 'numeric' })
