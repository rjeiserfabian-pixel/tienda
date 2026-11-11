// Lógica pura de los anticipos a proveedores: estados y validaciones del formulario.
// Los importes los calcula y valida SIEMPRE el servidor; aquí solo se revisan datos básicos.
import { hoyIso } from '../almacen/inventario'
import { aNumero } from '../almacen/utilidades'

export const ESTADOS_ANTICIPO = {
  EMITIDO: { texto: 'Vigente', clase: 'activo' },
  ANULADO: { texto: 'Anulado', clase: 'inactivo' },
}

const MONTO = /^\d+([.,]\d{1,2})?$/

/** Revisa monto, fecha y caja de un formulario de anticipo o de devolución. Devuelve { campo: mensaje }. */
export function validarDinero({ monto, cuenta, fecha, minimo = '', tope = null }) {
  const errores = {}
  const texto = String(monto ?? '').trim()
  if (!texto) errores.monto = 'Indique el monto.'
  else if (!MONTO.test(texto)) errores.monto = 'Use un número con hasta 2 decimales.'
  else if (!(aNumero(texto) > 0)) errores.monto = 'Debe ser mayor que cero.'
  else if (tope !== null && Math.round(aNumero(texto) * 100) > Math.round(tope * 100)) errores.monto = `No puede pasar de ${tope.toFixed(2)}.`
  if (!cuenta) errores.cuenta = 'Elija la caja o cuenta.'
  if (!fecha) errores.fecha = 'Indique la fecha.'
  else if (fecha > hoyIso()) errores.fecha = 'No puede ser futura.'
  else if (minimo && fecha < minimo) errores.fecha = 'No puede ser anterior al anticipo.'
  return errores
}
