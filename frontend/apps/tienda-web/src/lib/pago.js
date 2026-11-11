/**
 * Cobro con Culqi desde el navegador.
 *
 * La tarjeta (o el Yape) la captura el formulario de Culqi, NO esta tienda: de ahí solo sale un
 * «token» de un solo uso, que es lo único que se manda al servidor. Aquí nunca se guarda, se muestra
 * ni se escribe en consola nada de la tarjeta; tampoco el token (solo se pasa a la API).
 * El script de Culqi se descarga solo cuando el cliente va a pagar (no pesa en las demás páginas).
 */
const SCRIPT = 'https://checkout.culqi.com/js/v4'

let cargando = null

function cargarCulqi() {
  if (typeof window === 'undefined') return Promise.reject(new Error('sin navegador'))
  if (window.Culqi) return Promise.resolve(window.Culqi)
  if (!cargando) {
    cargando = new Promise((resolver, rechazar) => {
      const etiqueta = document.createElement('script')
      etiqueta.src = SCRIPT
      etiqueta.async = true
      etiqueta.onload = () => (window.Culqi ? resolver(window.Culqi) : rechazar(new Error('culqi')))
      etiqueta.onerror = () => {
        cargando = null // se podrá reintentar
        rechazar(new Error('culqi'))
      }
      document.head.appendChild(etiqueta)
    })
  }
  return cargando
}

/** Monto en céntimos enteros, sin errores de redondeo («1180.50» → 118050). */
export const centimos = (monto) => Math.round(Number(monto) * 100)

/**
 * Abre el formulario de Culqi. `alToken(tokenId)` se llama cuando el cliente completó sus datos;
 * `alError(mensaje)` si Culqi no pudo leerlos. Devuelve una función para cerrarlo.
 * Falla (promesa rechazada) si no se pudo descargar el script de Culqi.
 */
export async function abrirCulqi({ llavePublica, titulo, total, tarjeta = true, yape = true, alToken, alError }) {
  const Culqi = await cargarCulqi()
  Culqi.publicKey = llavePublica
  Culqi.settings({ title: String(titulo ?? 'Tienda').slice(0, 40), currency: 'PEN', amount: centimos(total) })
  Culqi.options({
    lang: 'auto',
    modal: true,
    installments: false,
    paymentMethods: { tarjeta, yape, bancaMovil: false, agente: false, billetera: false, cuotealo: false },
  })
  // Culqi llama a esta función global cuando hay un token o un error.
  window.culqi = () => {
    if (Culqi.token?.id) {
      const id = Culqi.token.id
      Culqi.close()
      alToken(id)
    } else if (Culqi.error) {
      const mensaje = Culqi.error.user_message || 'No pudimos leer los datos de tu pago. Revísalos e inténtalo de nuevo.'
      Culqi.close()
      alError(mensaje)
    }
  }
  Culqi.open()
  return () => {
    try {
      Culqi.close()
    } catch {
      // ya estaba cerrado
    }
  }
}

/** Estados del pedido: texto y color de la insignia. */
export const ESTADOS = {
  PENDIENTE_PAGO: { texto: 'Pendiente de pago', clase: 'poco' },
  PAGADO: { texto: 'Pagado', clase: 'ok' },
  EN_PREPARACION: { texto: 'En preparación', clase: 'ok' },
  LISTO_PARA_RECOJO: { texto: 'Listo para recoger', clase: 'ok' },
  ENVIADO: { texto: 'Enviado', clase: 'ok' },
  ENTREGADO: { texto: 'Entregado', clase: 'ok' },
  CANCELADO: { texto: 'Cancelado', clase: 'agotado' },
  EXPIRADO: { texto: 'Vencido sin pago', clase: 'agotado' },
  PAGADO_SIN_COMPROBANTE: { texto: 'Pagado, confirmando', clase: 'ok' },
  PAGADO_FUERA_DE_PLAZO: { texto: 'Pagado, en revisión', clase: 'poco' },
  REEMBOLSO_PENDIENTE: { texto: 'Reembolso en proceso', clase: 'poco' },
  REEMBOLSADO_PARCIAL: { texto: 'Reembolsado en parte', clase: 'poco' },
  REEMBOLSADO: { texto: 'Reembolsado', clase: 'poco' },
}

export const textoEstado = (estado) => ESTADOS[estado]?.texto ?? estado
export const claseEstado = (estado) => ESTADOS[estado]?.clase ?? ''

/** ¿Ya se cobró? (aunque falte el comprobante o la revisión). */
export const estaPagado = (estado) =>
  ['PAGADO', 'EN_PREPARACION', 'LISTO_PARA_RECOJO', 'ENVIADO', 'ENTREGADO', 'PAGADO_SIN_COMPROBANTE', 'PAGADO_FUERA_DE_PLAZO'].includes(estado)

export function fechaCorta(iso) {
  try {
    return new Intl.DateTimeFormat('es-PE', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso))
  } catch {
    return ''
  }
}
