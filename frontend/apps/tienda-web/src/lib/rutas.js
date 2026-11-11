/**
 * Ruta a la que volver después de ingresar. Solo se aceptan rutas internas de la tienda:
 * deben empezar con «/» (no «//»), sin «:», «\» ni espacios, para que nadie use el enlace
 * para mandar al cliente a otro sitio (open redirect).
 */
export function rutaSegura(volver, defecto = '/cuenta') {
  if (typeof volver !== 'string' || volver.length > 300) return defecto
  if (!volver.startsWith('/') || volver.startsWith('//')) return defecto
  if (volver.includes(':') || volver.includes('\\') || /\s/.test(volver)) return defecto
  return volver
}
