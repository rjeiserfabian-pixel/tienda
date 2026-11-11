import axios from 'axios'

const URL_REFRESH = '/seguridad/auth/refresh/'
// Rutas públicas: un 401 allí es una respuesta real (credenciales, desafío vencido), no una
// sesión caducada, así que NO se intenta renovar el token.
const RUTAS_SIN_REINTENTO = [
  '/seguridad/auth/login/',
  '/seguridad/auth/mfa/verificar/',
  '/seguridad/auth/recuperar/',
  URL_REFRESH,
]

// Cliente HTTP único. El access token vive SOLO en memoria (nunca en localStorage);
// el refresh viaja en una cookie HttpOnly que JavaScript no puede leer.
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api/v1',
  timeout: 15000,
  withCredentials: true,
  headers: { Accept: 'application/json' },
})

let accessToken = null
let alExpirarSesion = () => {}

export const guardarAccess = (token) => {
  accessToken = token
}
export const registrarExpiracion = (fn) => {
  alExpirarSesion = fn
}

api.interceptors.request.use((config) => {
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`
  return config
})

// Refresh con cola: aunque fallen varias peticiones a la vez, se renueva UNA sola vez.
let refrescando = null

async function renovarAccess() {
  if (!refrescando) {
    refrescando = (async () => {
      try {
        const { data } = await solicitarRefresh()
        accessToken = data.access
        return data
      } finally {
        refrescando = null
      }
    })()
  }
  return refrescando
}

// 409 = otra pestaña está rotando la cookie: se espera un instante y se reintenta una vez.
async function solicitarRefresh() {
  try {
    return await api.post(URL_REFRESH, {})
  } catch (error) {
    if (error.response?.status !== 409) throw error
    await new Promise((resolver) => setTimeout(resolver, 800))
    return api.post(URL_REFRESH, {})
  }
}

api.interceptors.response.use(
  (respuesta) => respuesta,
  async (error) => {
    const { config, response } = error
    const esReintentable =
      response?.status === 401 &&
      config &&
      !config._reintentada &&
      !RUTAS_SIN_REINTENTO.some((ruta) => config.url?.includes(ruta))

    if (!esReintentable) return Promise.reject(error)

    config._reintentada = true
    try {
      await renovarAccess()
    } catch (falloRefresh) {
      accessToken = null
      alExpirarSesion()
      return Promise.reject(falloRefresh)
    }
    return api(config)
  },
)

/** Restaura la sesión al abrir la app, usando la cookie de refresh. */
export async function restaurarSesion() {
  return renovarAccess()
}

/** Extrae el mensaje amigable del formato de error uniforme del backend. */
export function mensajeDeError(error) {
  return (
    error?.response?.data?.error?.mensaje ||
    (error?.code === 'ECONNABORTED' ? 'La solicitud tardó demasiado.' : null) ||
    (error?.request && !error?.response ? 'No hay conexión con el servidor.' : null) ||
    'No se pudo completar la operación. Intente nuevamente.'
  )
}

/** Errores por campo del backend (`error.detalle = {campo: [mensajes]}`) → `{campo: 'mensaje'}`. */
export function erroresDeCampo(error) {
  const detalle = error?.response?.data?.error?.detalle
  if (!detalle || Array.isArray(detalle) || typeof detalle !== 'object') return {}
  return Object.fromEntries(
    Object.entries(detalle).map(([campo, mensajes]) => [
      campo,
      Array.isArray(mensajes) ? mensajes.join(' ') : String(mensajes),
    ]),
  )
}

/** Código estable del error de dominio (p. ej. `ultimo_administrador`). */
export const codigoDeError = (error) => error?.response?.data?.error?.codigo ?? null
