/** Formato de precios y textos (es-PE). */

const SOLES = new Intl.NumberFormat('es-PE', {
  style: 'currency',
  currency: 'PEN',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

/** «1180.00» → «S/ 1,180.00». Devuelve `null` si no hay precio. */
export function soles(valor) {
  if (valor === null || valor === undefined || valor === '') return null
  const numero = Number(valor)
  return Number.isFinite(numero) ? SOLES.format(numero).replace(/\s/g, ' ') : null
}

/** Texto de la disponibilidad que ve el cliente. */
export function textoDisponibilidad(producto) {
  switch (producto.disponibilidad) {
    case 'agotado':
      return 'Agotado'
    case 'pocas':
      return producto.unidades === 1 ? 'Última unidad' : `Quedan ${producto.unidades} unidades`
    default:
      return 'Disponible'
  }
}

/** Las fotos que llegan de la API del navegador traen barra final: sin ella no hay redirección de Next. */
export const urlFoto = (url) => (typeof url === 'string' ? url.replace(/\/$/, '') : url)

/** Dirección absoluta de una ruta de la tienda (para enlaces compartidos y datos para Google). */
export function urlAbsoluta(ruta = '/') {
  const base = (process.env.SITE_URL || 'http://localhost:3000').replace(/\/$/, '')
  return `${base}${ruta}`
}

/**
 * Mensaje de WhatsApp ya escrito para consultar o comprar un producto.
 * El número lo administra el negocio en el panel (viene de la configuración de la tienda).
 */
export function enlaceWhatsapp(texto, numeroTienda) {
  const numero = String(numeroTienda ?? '').replace(/\D/g, '')
  if (!numero) return null
  return `https://wa.me/${numero}?text=${encodeURIComponent(texto)}`
}
