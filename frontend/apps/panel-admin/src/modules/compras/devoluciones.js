// Lógica pura de las pantallas de devoluciones a proveedores: borrador, cuerpo que recibe el servidor
// y validaciones. Los importes los calcula SIEMPRE el servidor (vista previa); aquí solo se arman
// y se revisan datos.
import { hoyIso, paraServidor } from '../almacen/inventario'
import { aNumero } from '../almacen/utilidades'

export const MOTIVOS = { TOTAL: 'Devolución total', POR_ITEM: 'Devolución por ítem' }

export const ESTADO_DEVOLUCION = {
  EMITIDO: { texto: 'Vigente', clase: 'activo' },
  ANULADO: { texto: 'Anulada', clase: 'inactivo' },
}

/** Céntimos enteros (o milésimas para cantidades): evita errores de coma flotante al comparar. */
const centimos = (n) => Math.round((n ?? 0) * 100)
const milesimas = (n) => Math.round((n ?? 0) * 1000)

export const borradorDevolucion = () => ({
  serie: '',
  numero: '',
  fecha: hoyIso(),
  razon: '',
  ajuste: '',
  filas: {}, // por línea de la compra: { cantidad: '', series: [] }
  reembolsar: false, // ¿el proveedor devuelve dinero de lo ya pagado?
})

/** Lo que se devuelve de una línea: con serie, tantas unidades como series; si no, lo escrito. */
export const cantidadFila = (fila, llevaSerie) => (llevaSerie ? (fila?.series?.length ?? 0) : (aNumero(fila?.cantidad) ?? 0))

/** Las líneas con algo que devolver, tal como las pide el cálculo y el registro. */
export function lineasPedidas(filas, lineas) {
  return lineas
    .map((l) => ({ linea: l.linea, cantidad: cantidadFila(filas[l.linea], l.lleva_serie), series: filas[l.linea]?.series ?? [], lleva_serie: l.lleva_serie }))
    .filter((p) => p.cantidad > 0)
}

const aLineasServidor = (pedidas, { conSeries }) =>
  pedidas.map((p) => ({
    linea: p.linea,
    cantidad: String(p.cantidad),
    ...(conSeries && p.lleva_serie ? { series: p.series } : {}),
  }))

const ajusteServidor = (ajuste) => (String(ajuste ?? '').trim() ? { ajuste_redondeo: paraServidor(ajuste) } : {})

/** Cuerpo de la vista previa: solo lo necesario para calcular. */
export const cuerpoCalculo = ({ empresa, compra, pedidas, ajuste }) => ({
  empresa,
  compra,
  lineas: aLineasServidor(pedidas, { conSeries: false }),
  ...ajusteServidor(ajuste),
})

/** Cuerpo del registro: la nota del proveedor, lo devuelto y el dinero que vuelve. */
export function cuerpoRegistro({ empresa, compra, b, pedidas, reembolsos }) {
  return {
    empresa,
    compra,
    ...(b.serie.trim() ? { comprobante_serie: b.serie.trim() } : {}),
    comprobante_numero: b.numero.trim(),
    fecha_emision: b.fecha,
    razon: b.razon.trim(),
    lineas: aLineasServidor(pedidas, { conSeries: true }),
    ...ajusteServidor(b.ajuste),
    ...(reembolsos.length
      ? {
          reembolsos: reembolsos.map((p) => ({
            medio_pago: Number(p.medio),
            cuenta: Number(p.cuenta),
            monto: paraServidor(p.monto),
            ...(p.pideReferencia || p.referencia.trim() ? { referencia: p.referencia.trim() } : {}),
            ...(p.otraMoneda ? { tipo_cambio: paraServidor(p.tipoCambio) } : {}),
          })),
        }
      : {}),
  }
}

/** Revisa lo escrito antes de enviar. `faltan` es la lista que se muestra junto al botón. */
export function validarDevolucion(b, lineas, pedidas, compra) {
  const campos = {}
  const faltan = []
  if (!b.numero.trim()) campos.numero = 'Indique el número de la nota de crédito.'
  if (!b.fecha) campos.fecha = 'Indique la fecha.'
  else if (b.fecha > hoyIso()) campos.fecha = 'No puede ser futura.'
  else if (b.fecha < compra.fecha_emision) campos.fecha = 'No puede ser anterior a la compra.'
  if (b.razon.trim().length < 3) campos.razon = 'Cuente por qué se devuelve.'
  if (String(b.ajuste ?? '').trim()) {
    const n = aNumero(b.ajuste)
    if (n === null || !/^-?\d+([.,]\d{1,2})?$/.test(String(b.ajuste).trim())) campos.ajuste = 'Hasta 2 decimales.'
    else if (Math.abs(n) > 0.1) campos.ajuste = 'El ajuste es de hasta 0.10.'
  }
  const porLinea = {}
  for (const l of lineas) {
    const fila = b.filas[l.linea]
    const escrita = String(fila?.cantidad ?? '').trim()
    if (l.lleva_serie) continue // se elige con las series: no puede pasarse
    if (!escrita) continue
    const n = aNumero(escrita)
    if (n === null || n <= 0) porLinea[l.linea] = 'Mayor que cero.'
    else if (!/^\d+([.,]\d{1,3})?$/.test(escrita)) porLinea[l.linea] = 'Hasta 3 decimales.'
    else if (milesimas(n) > milesimas(aNumero(l.pendiente))) porLinea[l.linea] = `Como máximo ${l.pendiente}.`
  }
  if (Object.keys(porLinea).length) faltan.push('Corregir las cantidades marcadas')
  if (!pedidas.length) faltan.push('Indicar qué productos se devuelven')
  if (campos.numero) faltan.push('El número de la nota de crédito del proveedor')
  if (campos.fecha) faltan.push('Una fecha válida')
  if (campos.razon) faltan.push('El motivo de la devolución')
  if (campos.ajuste) faltan.push('Corregir el ajuste de redondeo')
  return { campos, porLinea, faltan, valido: !faltan.length }
}

/** Revisa las filas de reembolso: método, caja o cuenta, monto, operación y que no pasen de lo pagado. */
export function validarReembolsos(resueltos, tope) {
  const porPago = {}
  for (const p of resueltos) {
    const e = {}
    const monto = aNumero(p.monto)
    if (!p.medio) e.medio = 'Elija el método.'
    if (!p.cuenta) e.cuenta = 'Elija la caja o cuenta.'
    if (monto === null || monto <= 0) e.monto = 'Mayor que cero.'
    else if (!/^\d+([.,]\d{1,2})?$/.test(String(p.monto).trim())) e.monto = 'Hasta 2 decimales.'
    if (p.pideReferencia && !p.referencia.trim()) e.referencia = 'Indique el N° de operación.'
    if (p.otraMoneda && !(aNumero(p.tipoCambio) > 0)) e.tipoCambio = 'Indique el tipo de cambio.'
    if (Object.keys(e).length) porPago[p.id] = e
  }
  const suma = resueltos.reduce((s, p) => s + centimos(aNumero(p.monto)), 0)
  const general = !Object.keys(porPago).length && suma > centimos(tope) ? 'El reembolso no puede pasar de lo que ya estaba pagado.' : ''
  return { porPago, general, valido: !Object.keys(porPago).length && !general }
}

/** A dónde fue el valor de la nota, para mostrarlo en una frase corta. */
export function destinoDelDinero(d) {
  const partes = []
  if (aNumero(d.aplicado_a_deuda) > 0) partes.push('rebajó la deuda')
  if (aNumero(d.reembolsado) > 0) partes.push('se reembolsó')
  if (aNumero(d.saldo_a_favor) > 0) partes.push('quedó a favor')
  return partes.length ? partes.join(' · ') : '—'
}
