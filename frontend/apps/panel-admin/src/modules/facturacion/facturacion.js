// Datos de la facturación electrónica: textos y colores de cada estado de envío.

export const ORIGENES = {
  COMPROBANTE: 'Facturas y boletas',
  NOTA_CREDITO: 'Notas de crédito',
  GUIA: 'Guías de remisión',
}

export const ESTADOS_ENVIO = {
  EN_PROCESO: { texto: 'Enviando', tono: 'azul' },
  ENVIADO: { texto: 'Enviado a la API', tono: 'verde' },
  ERROR_API: { texto: 'Error de la API', tono: 'rojo' },
  SIN_CONEXION: { texto: 'Sin conexión', tono: 'ambar' },
}

export const FILTROS_ENVIO = [
  ['', 'Todos'],
  ['sin_enviar', 'Sin enviar'],
  ['enviado', 'Enviados'],
  ['error', 'Con error'],
]

export const MODOS = {
  BETA: 'Beta (pruebas, sin efectos reales)',
  PRODUCCION: 'Producción (comprobantes oficiales)',
}

/** Fecha AAAA-MM-DD del servidor → 28/10/2026 (sin pasar por zonas horarias). */
export const fechaCorta = (iso) => {
  if (!iso) return '—'
  const [a, m, d] = String(iso).slice(0, 10).split('-')
  return a && m && d ? `${d}/${m}/${a}` : '—'
}

const FORMATO_DINERO = new Intl.NumberFormat('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** Importe del servidor (texto) → «118.00»; vacío si no aplica. */
export const importe = (valor) => {
  const n = Number(valor)
  return valor === null || valor === undefined || valor === '' || !Number.isFinite(n) ? '—' : FORMATO_DINERO.format(n)
}
