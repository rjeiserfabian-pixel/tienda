// Lógica pura de la pantalla «Pedidos» de la tienda: estados, pestañas y textos.

/** Cómo se ve cada estado del pedido (texto y color de la píldora). */
export const ESTADOS_PEDIDO = {
  PENDIENTE_PAGO: { texto: 'Sin pagar', tono: 'gris' },
  PAGADO: { texto: 'Pagado', tono: 'azul' },
  EN_PREPARACION: { texto: 'En preparación', tono: 'ambar' },
  LISTO_PARA_RECOJO: { texto: 'Listo para recoger', tono: 'cian' },
  ENVIADO: { texto: 'Enviado', tono: 'morado' },
  ENTREGADO: { texto: 'Entregado', tono: 'verde' },
  CANCELADO: { texto: 'Cancelado', tono: 'gris' },
  EXPIRADO: { texto: 'Vencido sin pago', tono: 'gris' },
  PAGADO_SIN_COMPROBANTE: { texto: 'Cobrado: falta comprobante', tono: 'rojo' },
  PAGADO_FUERA_DE_PLAZO: { texto: 'Pagó fuera de plazo', tono: 'rojo' },
  REEMBOLSO_PENDIENTE: { texto: 'Reembolso por confirmar', tono: 'rojo' },
  REEMBOLSADO_PARCIAL: { texto: 'Reembolsado en parte', tono: 'ambar' },
  REEMBOLSADO: { texto: 'Reembolsado', tono: 'gris' },
}

/** Pestañas de la lista: el valor es el «grupo» que entiende el servidor ('' = todos). */
export const PESTANAS_PEDIDOS = [
  { valor: 'por_atender', texto: 'Por atender' },
  { valor: 'listos', texto: 'Listos y enviados' },
  { valor: 'entregados', texto: 'Entregados' },
  { valor: 'reembolsados', texto: 'Reembolsados' },
  { valor: 'sin_pagar', texto: 'Sin pagar' },
  { valor: '', texto: 'Todos' },
]

export const MODALIDADES_PEDIDO = { ENVIO: 'Envío a domicilio', RECOJO: 'Recojo en tienda' }
export const MEDIOS_PAGO = { tarjeta: 'Tarjeta', yape: 'Yape' }
export const TIPOS_COMPROBANTE = { '03': 'Boleta', '01': 'Factura' }

/** Qué significa y qué hacer en los pedidos que requieren atención. */
export const AVISOS_ATENCION = {
  PAGADO_SIN_COMPROBANTE: {
    titulo: 'El cliente ya pagó, pero no se pudo emitir el comprobante.',
    texto:
      'El dinero está cobrado y el stock sigue apartado: no se perdió nada. Revisa el motivo, corrige lo que falta (por ejemplo, la serie de boletas o facturas de la empresa) y pulsa «Reintentar comprobante». El sistema también lo reintenta solo cada 5 minutos.',
  },
  PAGADO_FUERA_DE_PLAZO: {
    titulo: 'El cliente pagó cuando su pedido ya había vencido.',
    texto:
      'Se cobró el dinero pero el stock pudo haberse liberado y no se emitió ningún comprobante. Contacta al cliente y decide: atender el pedido a mano o devolverle el dinero con el botón «Reembolsar».',
  },
  REEMBOLSO_PENDIENTE: {
    titulo: 'El pedido ya se anuló o se devolvió en el sistema, pero Culqi aún no confirmó la devolución del dinero.',
    texto:
      'Los comprobantes y el stock ya están ajustados; falta que Culqi devuelva el dinero al cliente. El sistema lo reintenta solo cada 5 minutos y mientras tanto no puedes pedir otro reembolso de este pedido. Si el motivo persiste, revisa la llave de Culqi o el cargo en tu panel de Culqi y pulsa «Reintentar reembolso».',
  },
}

/** Qué hará el reembolso según su camino (para el modal). */
export const RUTAS_REEMBOLSO = {
  ANULACION: 'Se anula la venta',
  NOTA_CREDITO: 'Devolución con nota de crédito',
  SOLO_DINERO: 'Solo se devuelve el dinero',
}

/** Desde este monto (S/) se pide escribir el número del pedido para confirmar. */
export const MONTO_ALTO_REEMBOLSO = 1000

export const soles = (valor) => {
  const n = Number(valor)
  return Number.isFinite(n) ? `S/ ${n.toLocaleString('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'
}

/** Fecha y hora cortas en la hora del navegador: «10/11/2026 14:35». */
export const fechaHora = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const dos = (n) => String(n).padStart(2, '0')
  return `${dos(d.getDate())}/${dos(d.getMonth() + 1)}/${d.getFullYear()} ${dos(d.getHours())}:${dos(d.getMinutes())}`
}

/** Texto del botón que lleva al siguiente estado. */
export const textoAccion = (estado) =>
  ({
    EN_PREPARACION: 'Empezar a preparar',
    ENVIADO: 'Marcar como enviado',
    LISTO_PARA_RECOJO: 'Marcar listo para recoger',
    ENTREGADO: 'Marcar como entregado',
    CANCELADO: 'Cancelar pedido',
  })[estado] ?? estado

/** Ayuda bajo el campo de seguimiento, según el estado al que se pasa. */
export const ayudaSeguimiento = (estado) =>
  estado === 'ENVIADO'
    ? 'Guía, código de seguimiento o agencia. El cliente lo recibe por correo.'
    : estado === 'LISTO_PARA_RECOJO'
      ? 'Ej.: «Pregunta por Carlos en caja». El cliente lo recibe por correo.'
      : ''
