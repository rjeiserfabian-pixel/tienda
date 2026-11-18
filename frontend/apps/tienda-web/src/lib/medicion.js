/**
 * Medición (Google Analytics 4 y píxel de Meta). Solo funciona si el visitante aceptó las cookies y
 * el negocio puso sus códigos: en cualquier otro caso `medir` no hace nada. Nunca se envían datos
 * personales (ni nombre, ni correo, ni documento), solo productos, cantidades e importes.
 */
export const CLAVE_COOKIES = 'tienda:cookies:v1'

/** Evento propio (GA4) → evento estándar del píxel de Meta. */
const EVENTOS_META = {
  view_item: 'ViewContent',
  add_to_cart: 'AddToCart',
  begin_checkout: 'InitiateCheckout',
  purchase: 'Purchase',
}

export function leerConsentimiento() {
  try {
    const v = window.localStorage.getItem(CLAVE_COOKIES)
    return v === 'si' || v === 'no' ? v : null
  } catch {
    return null
  }
}

export function guardarConsentimiento(valor) {
  try {
    window.localStorage.setItem(CLAVE_COOKIES, valor)
  } catch {
    // sin almacenamiento: se vuelve a preguntar la próxima vez
  }
}

const cola = [] // eventos que llegaron antes de que se cargara la medición (se envían al cargarla)

/** Envía lo que esperaba en la cola; lo llama quien carga los scripts cuando ya están listos. */
export function vaciarCola() {
  while (cola.length) {
    const [evento, datos] = cola.shift()
    medir(evento, datos)
  }
}

/** `datos`: { value, currency, items: [{ item_id, item_name, price, quantity }], transaction_id }. */
export function medir(evento, datos = {}) {
  if (typeof window === 'undefined') return
  if (typeof window.gtag !== 'function' && typeof window.fbq !== 'function') {
    if (leerConsentimiento() !== 'no' && cola.length < 20) cola.push([evento, datos])
    return
  }
  try {
    if (typeof window.gtag === 'function') window.gtag('event', evento, datos)
    if (typeof window.fbq === 'function' && EVENTOS_META[evento]) {
      const items = datos.items ?? []
      window.fbq('track', EVENTOS_META[evento], {
        ...(datos.value !== undefined ? { value: datos.value, currency: datos.currency ?? 'PEN' } : {}),
        content_type: 'product',
        content_ids: items.map((i) => String(i.item_id)),
        num_items: items.reduce((s, i) => s + (i.quantity ?? 1), 0),
      })
    }
  } catch {
    // la medición nunca debe romper la tienda
  }
}
