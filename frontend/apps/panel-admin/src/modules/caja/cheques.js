// Lógica pura de las pantallas de cheques: tipos, estados, acciones posibles, vencimiento y
// validaciones. Los importes viajan como texto; el servidor decide siempre.
import { hoyIso, paraServidor } from '../almacen/inventario'

export const TIPOS_CHEQUE = {
  RECIBIDO: { texto: 'Recibido', largo: 'Recibido de un cliente' },
  EMITIDO: { texto: 'Girado', largo: 'Girado a un proveedor' },
}

export const ESTADOS_CHEQUE = {
  EN_CARTERA: { texto: 'En cartera', tono: 'azul' },
  DEPOSITADO: { texto: 'Depositado', tono: 'ambar' },
  GIRADO: { texto: 'Girado', tono: 'azul' },
  COBRADO: { texto: 'Cobrado', tono: 'verde' },
  RECHAZADO: { texto: 'Rechazado', tono: 'rojo' },
  ANULADO: { texto: 'Anulado', tono: 'gris' },
}

export const MONEDAS_CHEQUE = { PEN: 'Soles', USD: 'Dólares' }

/** Días antes del vencimiento desde los que se avisa (igual que el aviso de Caja). */
export const DIAS_AVISO = 5

const MS_DIA = 86_400_000
const aFecha = (iso) => new Date(`${iso}T00:00:00`)

/** Días que faltan para el vencimiento (negativo = ya pasó). */
export const diasParaVencer = (vence, hoy = hoyIso()) => Math.round((aFecha(vence) - aFecha(hoy)) / MS_DIA)

/** Un cheque pendiente es el que todavía hay que cobrar: solo a esos les importa vencer. */
export const estaPendiente = (c) => ['EN_CARTERA', 'DEPOSITADO', 'GIRADO'].includes(c.estado)

/** «vencido», «por_vencer» o '' según la fecha límite de un cheque recibido pendiente. */
export function situacionDeVencimiento(c, hoy = hoyIso()) {
  if (c.tipo !== 'RECIBIDO' || !estaPendiente(c) || !c.vence) return ''
  const dias = diasParaVencer(c.vence, hoy)
  if (dias < 0) return 'vencido'
  return dias <= DIAS_AVISO ? 'por_vencer' : ''
}

/**
 * Las acciones que admite un cheque según su tipo y estado (los permisos se revisan aparte).
 * Cada una trae el texto del botón y de la confirmación.
 */
export function accionesDeCheque(c) {
  const recibido = c.tipo === 'RECIBIDO'
  const lista = []
  if (recibido && c.estado === 'EN_CARTERA') lista.push('depositar')
  if (recibido && ['EN_CARTERA', 'DEPOSITADO'].includes(c.estado)) lista.push('cobrar')
  if (!recibido && c.estado === 'GIRADO') lista.push('cobrar')
  if (['EN_CARTERA', 'DEPOSITADO', 'GIRADO'].includes(c.estado)) lista.push('rechazar')
  if (['EN_CARTERA', 'GIRADO'].includes(c.estado)) lista.push('anular')
  if (c.estado === 'COBRADO') lista.push('deshacer')
  return lista
}

export const ACCIONES = {
  depositar: { boton: 'Depositar', icono: 'importar', titulo: 'Depositar el cheque' },
  cobrar: { boton: 'Cobrar', icono: 'coins', titulo: 'Marcar el cheque como cobrado' },
  rechazar: { boton: 'Rechazar', icono: 'cerrar', titulo: 'Rechazar el cheque' },
  anular: { boton: 'Anular', icono: 'papelera', titulo: 'Anular el cheque' },
  deshacer: { boton: 'Deshacer cobro', icono: 'reactivar', titulo: 'Deshacer el cobro' },
}

/** Texto aclaratorio de cada acción según el tipo de cheque. */
export function ayudaDeAccion(accion, c) {
  const recibido = c.tipo === 'RECIBIDO'
  if (accion === 'depositar') return 'Marca que el cheque se llevó al banco. Todavía no es dinero hasta que el banco lo pague.'
  if (accion === 'cobrar' && recibido) return 'El banco ya pagó el cheque: su importe pasa de la cuenta de cheques al banco que elijas.'
  if (accion === 'cobrar') return 'Un cheque girado no mueve dinero aquí: el pago al proveedor ya salió de la cuenta cuando se registró en Compras. Esto solo marca que el proveedor ya lo cobró.'
  if (accion === 'rechazar' && recibido) return 'El banco no pagó el cheque. Rechazarlo no mueve su importe; solo se anota, si quieres, la comisión que cobró el banco. La deuda del cliente hay que volver a abrirla desde Ventas.'
  if (accion === 'rechazar') return 'El banco no pagó el cheque que giraste. No se mueve dinero.'
  if (accion === 'anular' && recibido) return 'Úsalo si el cheque se devolvió o no vale. Solo se puede anular mientras sigue en cartera.'
  if (accion === 'anular') return 'Úsalo si el cheque no se entregó o se perdió. Si el pago ya se registró en Compras, anúlalo también allí.'
  return 'El dinero vuelve a la cuenta de cheques y el cheque regresa a su estado anterior.'
}

export const borradorCheque = () => ({
  tipo: 'RECIBIDO',
  numero: '',
  banco: '',
  importe: '',
  moneda: 'PEN',
  fecha_emision: hoyIso(),
  fecha_pago: '',
  tercero: '',
  cliente: null, // { id, nombre }
  proveedor: null,
  cuenta: '', // banco de giro (girado)
  cuenta_cartera: '', // cuenta de cheques (recibido)
  glosa: '',
})

/** Revisa en el navegador lo que se puede revisar antes de registrar un cheque. */
export function validarCheque(f, hoy = hoyIso()) {
  const e = {}
  if (!f.numero.trim()) e.numero = 'Indique el número del cheque.'
  if (!f.banco.trim()) e.banco = 'Indique el banco.'
  const importe = Number(paraServidor(f.importe))
  if (!paraServidor(f.importe) || !Number.isFinite(importe) || importe <= 0) e.importe = 'Mayor que cero.'
  else if (!/^\d+(\.\d{1,2})?$/.test(paraServidor(f.importe))) e.importe = 'Hasta 2 decimales.'
  if (!f.fecha_emision) e.fecha_emision = 'Indique la fecha.'
  else if (f.fecha_emision > hoy) e.fecha_emision = 'No puede ser futura.'
  if (f.fecha_pago && f.fecha_emision && f.fecha_pago < f.fecha_emision) e.fecha_pago = 'No puede ser anterior a la emisión.'
  if (!f.tercero.trim() && !f.cliente && !f.proveedor) e.tercero = f.tipo === 'RECIBIDO' ? 'Indique quién lo giró.' : 'Indique a quién se giró.'
  if (f.tipo === 'EMITIDO' && !f.cuenta) e.cuenta = 'Elija la cuenta de banco de giro.'
  return e
}

/** El cuerpo que recibe el servidor para registrar un cheque. */
export function cuerpoCheque(f, empresa) {
  const recibido = f.tipo === 'RECIBIDO'
  return {
    empresa,
    tipo: f.tipo,
    numero: f.numero.trim(),
    banco: f.banco.trim(),
    importe: paraServidor(f.importe),
    moneda: f.moneda,
    fecha_emision: f.fecha_emision,
    ...(f.fecha_pago ? { fecha_pago: f.fecha_pago } : {}),
    ...(f.tercero.trim() ? { tercero: f.tercero.trim() } : {}),
    ...(recibido && f.cliente ? { cliente: f.cliente.id } : {}),
    ...(!recibido && f.proveedor ? { proveedor: f.proveedor.id } : {}),
    ...(!recibido && f.cuenta ? { cuenta: Number(f.cuenta) } : {}),
    ...(recibido && f.cuenta_cartera ? { cuenta_cartera: Number(f.cuenta_cartera) } : {}),
    ...(f.glosa.trim() ? { glosa: f.glosa.trim() } : {}),
  }
}
