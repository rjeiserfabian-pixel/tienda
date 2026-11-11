/**
 * Llamadas a la API de la tienda DESDE EL NAVEGADOR (cuenta, carrito, compra).
 *
 * Van a la misma dirección de la tienda (`/api/v1/tienda/...`, que Next reenvía a la API), así la
 * cookie de sesión HttpOnly viaja sola y no hace falta CORS. Las rutas van SIN barra final (Next la
 * redirige y un POST perdería datos). Las operaciones que cambian algo llevan la cabecera
 * `X-Requested-With: tienda`, que la API exige contra el CSRF.
 */
export class ErrorTienda extends Error {
  constructor(estado, codigo, mensaje, campos = null) {
    super(mensaje)
    this.name = 'ErrorTienda'
    this.estado = estado
    this.codigo = codigo
    /** Errores por campo, si la API los trae: { correo: ['…'], password: ['…'] } */
    this.campos = campos
  }
}

const SIN_CONEXION = 'No pudimos conectar con la tienda. Revisa tu internet e inténtalo de nuevo.'
const GENERICO = 'Algo salió mal. Inténtalo de nuevo en un momento.'

/** Llama a la API. Devuelve el JSON, o lanza un `ErrorTienda` con un mensaje listo para mostrar. */
export async function llamar(ruta, { metodo = 'GET', cuerpo, signal } = {}) {
  let respuesta
  try {
    respuesta = await fetch(`/api/v1/tienda/${ruta}`, {
      method: metodo,
      headers: {
        Accept: 'application/json',
        'X-Requested-With': 'tienda',
        ...(cuerpo === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
      credentials: 'same-origin',
      cache: 'no-store',
      signal,
    })
  } catch (error) {
    if (error?.name === 'AbortError') throw error
    throw new ErrorTienda(0, 'sin_conexion', SIN_CONEXION)
  }
  let datos = null
  try {
    datos = await respuesta.json()
  } catch {
    // respuesta sin cuerpo JSON
  }
  if (!respuesta.ok) {
    const error = datos?.error
    const campos = error?.detalle && typeof error.detalle === 'object' ? error.detalle : null
    throw new ErrorTienda(respuesta.status, error?.codigo ?? 'error', mensajeDe(error, campos), campos)
  }
  return datos
}

/** El mensaje más útil: el primer error de campo si hay, si no el general de la API. */
function mensajeDe(error, campos) {
  if (campos) {
    const primero = Object.values(campos).flat()[0]
    if (typeof primero === 'string') return primero
  }
  return error?.mensaje || GENERICO
}

/** Texto del primer error de un campo (o `undefined`). */
export function errorDeCampo(error, campo) {
  const lista = error?.campos?.[campo]
  return Array.isArray(lista) ? lista[0] : typeof lista === 'string' ? lista : undefined
}
