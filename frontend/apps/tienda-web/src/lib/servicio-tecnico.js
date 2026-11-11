/**
 * Seguimiento del servicio técnico desde la tienda.
 *
 * La API pública del servicio técnico (`/api/v1/servicio-tecnico/publico/<token>/`) solo devuelve lo
 * que el cliente puede ver: código, equipo, en qué paso va, fechas, mensaje del taller y datos de
 * contacto. Nunca precios, diagnóstico, notas internas ni datos del cliente.
 *
 * El enlace secreto (token) es la única llave: por eso estas consultas NUNCA se guardan en la caché
 * de Next ni se comparten, y todo token se valida con el mismo formato estricto que la API antes de
 * usarlo.
 */
const API_URL = process.env.API_URL || 'http://localhost:8000'
const ESPERA_MS = 8000

/** Mismo formato que acepta la API: letras, números, guion y guion bajo, de 8 a 40 caracteres. */
export const FORMATO_TOKEN = /^[A-Za-z0-9_-]{8,40}$/
const LARGO_MAXIMO_ENTRADA = 300

/**
 * Saca el token de lo que pegó el cliente: el código solo o el enlace completo de su hoja
 * (`…/estado/<código>` o `…/servicio-tecnico/<código>`). Devuelve `null` si no hay un token válido.
 */
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
  for (const marca of ['estado', 'servicio-tecnico']) {
    const i = trozos.lastIndexOf(marca)
    if (i >= 0 && trozos.length === i + 2) {
      let candidato
      try {
        candidato = decodeURIComponent(trozos[i + 1])
      } catch {
        return null
      }
      return FORMATO_TOKEN.test(candidato) ? candidato : null
    }
  }
  return null
}

/**
 * Consulta el estado de una orden (solo servidor). Devuelve siempre un objeto con `situacion`:
 * `ok` (con `datos`), `no_encontrado`, `limitado` (demasiadas consultas) o `error`.
 */
export async function obtenerEstadoServicio(token) {
  if (!FORMATO_TOKEN.test(token ?? '')) return { situacion: 'no_encontrado' }
  const url = new URL(`/api/v1/servicio-tecnico/publico/${encodeURIComponent(token)}/`, API_URL)
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

/**
 * Las 6 etapas que ve el cliente (los 13 estados internos se agrupan). Las salidas que no son el
 * camino normal (no aprobado, sin solución, abandonado) no tienen etapa: se muestran como aviso.
 */
export const ETAPAS = [
  { id: 'recibido', titulo: 'Recibido', claves: ['RECIBIDO'] },
  { id: 'revision', titulo: 'En revisión', claves: ['PENDIENTE_DIAGNOSTICO', 'EN_DIAGNOSTICO', 'DIAGNOSTICADO'] },
  { id: 'presupuesto', titulo: 'Presupuesto', claves: ['PENDIENTE_APROBACION', 'APROBADO'] },
  { id: 'trabajo', titulo: 'En trabajo', claves: ['EN_MANTENIMIENTO', 'EN_REPARACION', 'PENDIENTE_REPUESTO', 'EN_PRUEBAS', 'TERMINADO'] },
  { id: 'listo', titulo: 'Listo para recoger', claves: ['LISTO_ENTREGA'] },
  { id: 'entregado', titulo: 'Entregado', claves: ['ENTREGADO'] },
]

export const SALIDAS = ['NO_APROBADO', 'SIN_SOLUCION', 'ABANDONADO']
export const ESTADOS_FINALES = ['ENTREGADO', ...SALIDAS]

/** Posición de la etapa actual (0 a 5), o -1 si el estado es una salida o no se conoce. */
export function etapaActual(clave) {
  return ETAPAS.findIndex((e) => e.claves.includes(clave))
}

const FORMATO_FECHA_HORA = new Intl.DateTimeFormat('es-PE', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: true,
  timeZone: 'America/Lima',
})
const FORMATO_FECHA = new Intl.DateTimeFormat('es-PE', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
  timeZone: 'America/Lima',
})

/** «2026-11-10T15:04:00-05:00» → «10 nov 2026, 03:04 p. m.». Devuelve `null` si no es una fecha. */
export function fechaHora(valor) {
  const d = new Date(valor)
  return Number.isNaN(d.getTime()) ? null : FORMATO_FECHA_HORA.format(d)
}

/** «2026-11-10» → «10 de noviembre de 2026» (sin correr el día por zona horaria). */
export function fechaDia(valor) {
  if (typeof valor !== 'string' || !/^\d{4}-\d{2}-\d{2}/.test(valor)) return null
  const d = new Date(`${valor.slice(0, 10)}T12:00:00-05:00`)
  return Number.isNaN(d.getTime()) ? null : FORMATO_FECHA.format(d)
}

/** Deja solo dígitos y «+» para un enlace `tel:`; `null` si no queda nada útil. */
export function telefonoLimpio(valor) {
  const limpio = String(valor ?? '').replace(/[^\d+]/g, '')
  return limpio.replace(/\D/g, '').length >= 6 ? limpio : null
}
