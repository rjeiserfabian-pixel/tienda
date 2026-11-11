// Lógica pura de las pantallas de gastos (sin React): importes, validación y cuerpo para el servidor.
import { aNumero } from '../almacen/utilidades'
import { paraServidor } from '../almacen/inventario'
import { dinero, nuevoPago, totalPagado } from '../compras/compras'

export { dinero, nuevoPago }

const centimos = (valor) => Math.round(Number(valor) * 100)
const aSoles = (c) => c / 100

export const FORMAS_PAGO = { CONTADO: 'Al contado', POR_PAGAR: 'Por pagar' }

/** Cómo está un gasto en cuanto a su pago (lo calcula el servidor; aquí solo cómo se muestra). */
export const ESTADOS_PAGO = {
  PAGADO: { texto: 'Pagado', tono: 'verde' },
  PARCIAL: { texto: 'Pago parcial', tono: 'ambar' },
  PENDIENTE: { texto: 'Por pagar', tono: 'azul' },
  VENCIDO: { texto: 'Vencido', tono: 'rojo' },
  ANULADO: { texto: 'Anulado', tono: 'gris' },
}

export const borradorInicial = (hoy) => ({
  conComprobante: true,
  fecha: hoy,
  categoria: '',
  descripcion: '',
  tipo: '',
  serie: '',
  numero: '',
  proveedor: null,
  base: '',
  igv: '',
  igvManual: false,
  noGravado: '',
  importe: '',
  gastadoPor: '',
  moneda: 'PEN',
  tipoCambio: '',
  forma: 'CONTADO',
  vence: '',
  pagos: [nuevoPago()],
  repartir: false,
  reparto: [],
  sucursal: '',
  observacion: '',
  recurrente: null,
})

/** El IGV que corresponde a una base, a la tasa vigente (porcentaje): redondeado al centavo. */
export const igvDe = (base, tasa) => aSoles(Math.round((centimos(aNumero(base)) * Number(tasa)) / 100))

/**
 * Los importes del gasto según lo que se escribió. Un comprobante que detalla el IGV lleva base, IGV
 * (que se propone solo) e importe sin IGV; los demás casos (boleta sin detalle, recibo, un taxi) llevan
 * un solo importe. Devuelve montos en soles/dólares ya sumados, sin errores de decimales.
 */
export function importesDe(b, detallaIgv, tasa) {
  if (b.conComprobante && detallaIgv) {
    const base = aNumero(b.base) ?? 0
    const igv = b.igvManual ? (aNumero(b.igv) ?? 0) : igvDe(base, tasa)
    const noGravado = aNumero(b.noGravado) ?? 0
    return { base, igv, noGravado, total: aSoles(centimos(base) + centimos(igv) + centimos(noGravado)) }
  }
  const importe = aNumero(b.importe) ?? 0
  return { base: 0, igv: 0, noGravado: importe, total: importe }
}

/** El reparto entre empresas: porcentajes escritos → suma, y qué falta para llegar a 100. */
export function resumenReparto(reparto) {
  const suma = reparto.reduce((s, r) => s + centimos(aNumero(r.porcentaje)), 0)
  return { suma: aSoles(suma), falta: aSoles(10000 - suma) }
}

/** Reparto por defecto al activarlo: la empresa que registra y otra, mitad y mitad. */
export function repartoInicial(empresas, empresaId) {
  const propia = empresas.find((e) => e.id === empresaId)
  const otra = empresas.find((e) => e.id !== empresaId)
  if (!propia || !otra) return []
  return [
    { empresa: String(propia.id), porcentaje: '50' },
    { empresa: String(otra.id), porcentaje: '50' },
  ]
}

const FECHA_ISO = /^\d{4}-\d{2}-\d{2}$/

/**
 * Lo que se puede revisar en el navegador antes de enviar (el servidor revisa todo otra vez).
 * Devuelve `{ errores, faltan, valido }`: los errores por campo y la lista de lo que falta.
 */
export function validarGasto(b, ctx) {
  const { detallaIgv, total, tope, puedeExceder, hoy, pagos, errPagos, tipoComprobante, repartoActivo } = ctx
  const e = {}
  const faltan = []
  const pedir = (campo, mensaje, falta) => {
    e[campo] = mensaje
    faltan.push(falta ?? mensaje)
  }

  if (!b.categoria) pedir('categoria', 'Elija la categoría.', 'La categoría')
  if (b.descripcion.trim().length < 3) pedir('descripcion', 'Describa qué fue y para qué.', 'Qué fue el gasto')
  if (!FECHA_ISO.test(b.fecha) || b.fecha > hoy) pedir('fecha', 'La fecha no puede ser futura.', 'Una fecha válida')

  if (b.conComprobante) {
    if (!tipoComprobante) pedir('tipo', 'Elija el tipo de comprobante.', 'El tipo de comprobante')
    if (!b.numero.trim()) pedir('numero', 'Indique el número del comprobante.', 'El número del comprobante')
    else if (!/^[A-Za-z0-9][A-Za-z0-9-]{0,19}$/.test(b.numero.trim())) e.numero = 'Solo letras, números y guion.'
    if (b.serie.trim() && !/^[A-Za-z0-9]{1,10}$/.test(b.serie.trim())) e.serie = 'Solo letras y números (hasta 10).'
    if (tipoComprobante?.codigo === '01' && !b.proveedor) pedir('proveedor', 'Una factura necesita el proveedor.', 'El proveedor')
    if (detallaIgv) {
      if (!(aNumero(b.base) > 0) && !(aNumero(b.noGravado) > 0)) pedir('base', 'Escriba la base o el importe sin IGV.', 'El importe del comprobante')
    } else if (!(aNumero(b.importe) > 0)) {
      pedir('importe', 'Escriba el importe.', 'El importe')
    }
  } else {
    if (b.gastadoPor.trim().length < 2) pedir('gastadoPor', 'Indique quién hizo el gasto.', 'Quién hizo el gasto')
    if (!(aNumero(b.importe) > 0)) pedir('importe', 'Escriba el importe.', 'El importe')
  }
  if (!(total > 0) && !e.importe && !e.base) pedir('importe', 'El total debe ser mayor que cero.', 'Un importe mayor que cero')

  if (!b.conComprobante && total > 0 && tope !== null && !puedeExceder) {
    const enSoles = b.moneda === 'USD' ? total * aNumero(b.tipoCambio || 0) : total
    if (enSoles > tope) pedir('importe', `Sin comprobante el tope es S/ ${tope.toFixed(2)}. Pida el comprobante o a quien pueda autorizarlo.`, 'Bajar el importe o conseguir el comprobante')
  }
  if (b.moneda === 'USD' && !(aNumero(b.tipoCambio) > 0)) pedir('tipoCambio', 'Indique el tipo de cambio.', 'El tipo de cambio')

  if (b.forma === 'POR_PAGAR') {
    if (!FECHA_ISO.test(b.vence) || b.vence < b.fecha) pedir('vence', 'El vencimiento no puede ser anterior al gasto.', 'La fecha de vencimiento')
  } else {
    const pagado = totalPagado(pagos)
    if (Math.abs(pagado - total) > 0.001 || pagado <= 0) faltan.push('Que los pagos sumen el total')
    if (Object.keys(errPagos).length > 0) faltan.push('Completar los datos del pago')
  }

  if (repartoActivo) {
    const { suma } = resumenReparto(b.reparto)
    const vistos = new Set()
    const repetida = b.reparto.some((r) => (vistos.has(r.empresa) ? true : !vistos.add(r.empresa)))
    if (b.reparto.length < 2 || b.reparto.some((r) => !r.empresa || !(aNumero(r.porcentaje) > 0))) pedir('reparto', 'Elija las empresas y su porcentaje.', 'El reparto entre empresas')
    else if (repetida) pedir('reparto', 'Una empresa aparece dos veces.', 'Una empresa por fila del reparto')
    else if (Math.abs(suma - 100) > 0.001) pedir('reparto', `Los porcentajes suman ${suma}%: deben sumar 100%.`, 'Que el reparto sume 100%')
  }
  return { errores: e, faltan, valido: faltan.length === 0 }
}

/** Revisa los pagos ya resueltos (método, caja, monto, referencia, tipo de cambio) y devuelve los errores por pago. */
export function erroresDePagos(pagos) {
  const porPago = {}
  for (const p of pagos) {
    const e = {}
    if (!p.medio) e.medio = 'Elija el método.'
    if (!p.cuenta) e.cuenta = 'Elija la caja o cuenta.'
    if (!(aNumero(p.monto) > 0)) e.monto = 'Mayor que cero.'
    if (p.pideReferencia && !p.referencia.trim()) e.referencia = 'Indique el N° de operación.'
    if (p.otraMoneda && !(aNumero(p.tipoCambio) > 0)) e.tipoCambio = 'Indique el tipo de cambio.'
    if (Object.keys(e).length) porPago[p.id] = e
  }
  return porPago
}

/** Cuerpo que se envía al servidor: solo lo que aplica al caso (con o sin comprobante, contado o por pagar). */
export function armarCuerpo(b, ctx) {
  const { empresa, importes, pagos, tipoComprobante, repartoActivo } = ctx
  const cuerpo = {
    empresa,
    categoria: Number(b.categoria),
    fecha: b.fecha,
    descripcion: b.descripcion.trim(),
    con_comprobante: b.conComprobante,
    moneda: b.moneda,
    forma_pago: b.forma,
    base_gravada: paraServidor(importes.base.toFixed(2)),
    igv: paraServidor(importes.igv.toFixed(2)),
    no_gravado: paraServidor(importes.noGravado.toFixed(2)),
  }
  if (b.moneda === 'USD') cuerpo.tipo_cambio = paraServidor(b.tipoCambio)
  if (b.conComprobante) {
    cuerpo.tipo_comprobante = tipoComprobante.id
    cuerpo.comprobante_serie = b.serie.trim()
    cuerpo.comprobante_numero = b.numero.trim()
    if (b.proveedor) cuerpo.proveedor = b.proveedor.id
  } else {
    cuerpo.gastado_por = b.gastadoPor.trim()
  }
  if (b.sucursal) cuerpo.sucursal = Number(b.sucursal)
  if (b.recurrente) cuerpo.recurrente = b.recurrente
  if (b.observacion.trim()) cuerpo.observacion = b.observacion.trim()
  if (b.forma === 'POR_PAGAR') {
    cuerpo.fecha_vencimiento = b.vence
  } else {
    cuerpo.pagos = pagos.map((p) => ({
      medio_pago: Number(p.medio),
      cuenta: Number(p.cuenta),
      monto: paraServidor(p.monto),
      ...(p.pideReferencia || p.referencia.trim() ? { referencia: p.referencia.trim() } : {}),
      ...(p.otraMoneda ? { tipo_cambio: paraServidor(p.tipoCambio) } : {}),
      ...(p.aporte ? { aporte_socio: true } : {}),
    }))
  }
  if (repartoActivo) cuerpo.reparto = b.reparto.map((r) => ({ empresa: Number(r.empresa), porcentaje: paraServidor(r.porcentaje) }))
  return cuerpo
}

/** Cómo se muestra el aviso de un gasto recurrente (lo calcula el servidor). */
export const AVISOS_RECURRENTE = {
  VENCIDO: { texto: 'Atrasado', tono: 'rojo' },
  HOY: { texto: 'Toca hoy', tono: 'ambar' },
  PROXIMO: { texto: 'Toca pronto', tono: 'ambar' },
  AL_DIA: { texto: 'Al día', tono: 'verde' },
  INACTIVO: { texto: 'Inactivo', tono: 'gris' },
}

/** «hace 3 días», «hoy», «en 5 días»: lo que falta o lo que pasó desde la fecha en que tocaba. */
export function textoDeDias(dias) {
  if (dias === 0) return 'hoy'
  const n = Math.abs(dias)
  const unidad = n === 1 ? 'día' : 'días'
  return dias < 0 ? `hace ${n} ${unidad}` : `en ${n} ${unidad}`
}

/** Lo que se puede revisar antes de guardar un gasto recurrente (el servidor revisa todo otra vez). */
export function validarRecurrente(f) {
  const e = {}
  if (f.nombre.trim().length < 3) e.nombre = 'Ponga un nombre (por ejemplo, Alquiler del local).'
  if (!f.categoria) e.categoria = 'Elija la categoría.'
  if (f.descripcion.trim().length < 3) e.descripcion = 'Describa qué es y para qué.'
  if (!f.periodicidad) e.periodicidad = 'Elija cada cuánto se repite.'
  if (!/^\d{4}-\d{2}-\d{2}$/.test(f.proxima)) e.proxima = 'Indique cuándo le toca.'
  const importe = String(f.importe).trim().replace(',', '.')
  if (importe && (!/^\d{1,14}(\.\d{1,2})?$/.test(importe) || Number(importe) <= 0)) e.importe = 'Un número mayor que cero, con hasta 2 decimales.'
  const aviso = Number(f.avisar)
  if (!Number.isInteger(aviso) || aviso < 0 || aviso > 30) e.avisar = 'De 0 a 30 días.'
  return e
}

/**
 * Lo que se propone al registrar un gasto desde su plantilla. El importe habitual es el total: con
 * un comprobante que detalla el IGV se separa la base; si no, va como importe único.
 */
export function borradorDeRecurrente(base, r, { detallaIgv, tasa }) {
  const total = r.importe_estimado ? Number(r.importe_estimado) : null
  const propuesto = { importe: '', base: '', igv: '', igvManual: false, noGravado: '' }
  if (total !== null) {
    if (r.con_comprobante && detallaIgv) propuesto.base = (Math.round((total * 100) / (1 + Number(tasa) / 100)) / 100).toFixed(2)
    else propuesto.importe = total.toFixed(2)
  }
  return {
    ...base,
    ...propuesto,
    conComprobante: r.con_comprobante,
    categoria: String(r.categoria),
    descripcion: r.descripcion,
    tipo: r.tipo_comprobante ? String(r.tipo_comprobante) : '',
    proveedor: r.proveedor ? { id: r.proveedor, nombre: r.proveedor_nombre, tipo_documento: r.proveedor_tipo_documento, numero_documento: r.proveedor_documento } : null,
    moneda: r.moneda,
    recurrente: r.id,
  }
}
