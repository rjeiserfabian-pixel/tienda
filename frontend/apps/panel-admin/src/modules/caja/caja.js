// Lógica pura de las pantallas de caja y bancos.
import { dinero } from '../compras/compras'

export const TIPOS = { INGRESO: 'Ingreso', EGRESO: 'Egreso' }

/** De dónde viene un movimiento: lo que escribió una persona o lo que generó otro módulo. */
export const ORIGENES = {
  MANUAL: { texto: 'Manual', tono: 'gris' },
  PAGO_COMPRA: { texto: 'Pago de compra', tono: 'azul' },
  PAGO_GASTO: { texto: 'Pago de gasto', tono: 'azul' },
  COBRO_VENTA: { texto: 'Cobro de venta', tono: 'verde' },
  ABONO_VENTA: { texto: 'Abono de cliente', tono: 'verde' },
  COMISION_TARJETA: { texto: 'Comisión de tarjetas', tono: 'naranja' },
  REEMBOLSO_VENTA: { texto: 'Devolución a cliente', tono: 'naranja' },
  REEMBOLSO_COMPRA: { texto: 'Devolución de proveedor', tono: 'verde' },
  ADELANTO_SERVICIO: { texto: 'Adelanto de servicio', tono: 'verde' },
  DEVOLUCION_ADELANTO: { texto: 'Devolución de adelanto', tono: 'naranja' },
  ADELANTO_PERSONAL: { texto: 'Adelanto a trabajador', tono: 'naranja' },
  PAGO_PLANILLA: { texto: 'Pago de sueldos', tono: 'naranja' },
  TRANSFERENCIA: { texto: 'Transferencia', tono: 'morado' },
  ARQUEO: { texto: 'Arqueo', tono: 'naranja' },
  EXTRACTO: { texto: 'Del banco', tono: 'azul' },
  APORTE_PAGO_COMPRA: { texto: 'Aporte del socio', tono: 'morado' },
  APORTE_PAGO_GASTO: { texto: 'Aporte del socio', tono: 'morado' },
}

export const origen = (tipo) => ORIGENES[tipo] ?? { texto: 'Automático', tono: 'azul' }

export { dinero }

/** Cuentas en grupos para mostrarlas: cajas, bancos y billeteras. */
export const GRUPOS_DE_CUENTA = [
  ['CAJA', 'Cajas de efectivo'],
  ['BANCO', 'Cuentas de banco'],
  ['BILLETERA', 'Billeteras digitales'],
]

/** Revisa lo que se puede revisar en el navegador antes de registrar un movimiento a mano. */
export function validarMovimiento(f, hoy) {
  const e = {}
  if (!f.cuenta) e.cuenta = 'Elija la caja o cuenta.'
  if (!f.concepto) e.concepto = 'Elija el concepto.'
  const monto = Number(String(f.monto).replace(',', '.'))
  if (!String(f.monto).trim() || !Number.isFinite(monto) || monto <= 0) e.monto = 'Mayor que cero.'
  else if (!/^\d+([.,]\d{1,2})?$/.test(String(f.monto).trim())) e.monto = 'Hasta 2 decimales.'
  if (!f.fecha) e.fecha = 'Indique la fecha.'
  else if (f.fecha > hoy) e.fecha = 'No puede ser futura.'
  return e
}

/** Lo que se puede hacer al mover dinero entre cuentas, con su texto de ayuda y su botón. */
export const CLASES = {
  DEPOSITO: { titulo: 'Depósito', ayuda: 'Del efectivo de una caja a una cuenta de banco o billetera.', boton: 'Registrar depósito' },
  RETIRO: { titulo: 'Retiro', ayuda: 'De una cuenta de banco o billetera al efectivo de una caja.', boton: 'Registrar retiro' },
  TRANSFERENCIA: { titulo: 'Transferencia', ayuda: 'Entre cualquier par de cajas y cuentas, incluso de soles a dólares o a otra empresa.', boton: 'Registrar transferencia' },
}

/** Monto en la otra moneda: soles → dólares divide entre el tipo de cambio; dólares → soles multiplica. */
export const convertir = (monto, de, a, tipoCambio) => {
  if (de === a) return monto
  return Math.round((de === 'PEN' ? monto / tipoCambio : monto * tipoCambio) * 100) / 100
}

/** Revisa en el navegador lo que se puede antes de mover dinero; el servidor vuelve a validar todo. */
export function validarTransferencia(f, { origen, destino, cambiaMoneda }, hoy) {
  const e = {}
  if (!origen) e.origen = 'Elija de dónde sale.'
  if (!destino) e.destino = 'Elija a dónde entra.'
  const num = (t) => Number(String(t).replace(',', '.'))
  const dosDecimales = (t) => /^\d+([.,]\d{1,2})?$/.test(String(t).trim())
  if (!String(f.monto).trim() || !(num(f.monto) > 0)) e.monto = 'Mayor que cero.'
  else if (!dosDecimales(f.monto)) e.monto = 'Hasta 2 decimales.'
  if (cambiaMoneda && !(num(f.tipoCambio) > 0)) e.tipoCambio = 'Indique el tipo de cambio.'
  if (!f.fecha) e.fecha = 'Indique la fecha.'
  else if (f.fecha > hoy) e.fecha = 'No puede ser futura.'
  for (const campo of ['comision', 'itf']) {
    if (String(f[campo]).trim() && !dosDecimales(f[campo])) e[campo] = 'Hasta 2 decimales.'
  }
  return e
}

/** Billetes y monedas que se cuentan al arquear, por moneda (de mayor a menor). */
export const DENOMINACIONES = {
  PEN: ['200', '100', '50', '20', '10', '5', '2', '1', '0.5', '0.2', '0.1'],
  USD: ['100', '50', '20', '10', '5', '2', '1'],
}

/** Una denominación menor que 5 es moneda; el resto, billete (en dólares todo es billete). */
export const esMoneda = (denominacion, moneda) => moneda === 'PEN' && Number(denominacion) <= 5

/** Total contado, en céntimos enteros para no acumular errores de decimales. */
export function totalContado(conteo) {
  let centimos = 0
  for (const [denominacion, cantidad] of Object.entries(conteo)) {
    const n = Number.parseInt(cantidad, 10)
    if (Number.isFinite(n) && n > 0) centimos += Math.round(Number(denominacion) * 100) * n
  }
  return centimos / 100
}

/** Lo que se envía: solo las denominaciones con cantidad, como números enteros. */
export function conteoParaEnviar(conteo) {
  const limpio = {}
  for (const [denominacion, cantidad] of Object.entries(conteo)) {
    const n = Number.parseInt(cantidad, 10)
    if (Number.isFinite(n) && n > 0) limpio[denominacion] = n
  }
  return limpio
}

/** Cantidades válidas: enteros desde 0. Devuelve el mensaje del primer error, o '' si está bien. */
export function validarConteo(conteo) {
  for (const cantidad of Object.values(conteo)) {
    if (String(cantidad).trim() === '') continue
    if (!/^\d{1,7}$/.test(String(cantidad).trim())) return 'Las cantidades son números enteros, desde 0.'
  }
  return ''
}

/** Cómo quedó una cuenta: cuadra, sobra o falta (en céntimos para comparar sin errores). */
export function resultadoDeConteo(contado, esperado) {
  const diferencia = Math.round((Number(contado) - Number(esperado)) * 100) / 100
  if (diferencia === 0) return { tipo: 'cuadra', diferencia }
  return { tipo: diferencia > 0 ? 'sobra' : 'falta', diferencia }
}

export const ESTADOS_SESION = {
  ABIERTA: { texto: 'Abierta', clase: 'activo' },
  CERRADA: { texto: 'Cerrada', clase: 'inactivo' },
}

export const ROLES_CAJA = { PRINCIPAL: 'Caja principal', MOSTRADOR: 'Mostrador', CAJA_CHICA: 'Caja chica' }

export const ESTADOS_CONCILIACION = {
  ABIERTO: { texto: 'En proceso', clase: 'pendiente' },
  CERRADO: { texto: 'Conciliado', clase: 'activo' },
}

/** Una línea del banco es un abono (entra dinero) o un cargo (sale). */
export const esAbono = (monto) => Number(monto) > 0

/** Qué dice la diferencia de un resumen: cuadra, o cuánto falta explicar. */
export function estadoDeDiferencia(diferencia) {
  if (diferencia === null || diferencia === undefined) return { tipo: 'sin-saldo', texto: 'Sin saldo del banco para comparar' }
  return Number(diferencia) === 0 ? { tipo: 'cuadra', texto: 'Cuadra con el banco' } : { tipo: 'difiere', texto: 'Hay una diferencia sin explicar' }
}

/** Validaciones de la ventana de importar, antes de pedir nada al servidor. */
export function validarImportacion({ cuenta, archivo, saldoInicial, saldoFinal }) {
  const e = {}
  if (!cuenta) e.cuenta = 'Elija la cuenta del banco.'
  if (!archivo) e.archivo = 'Elija el archivo del banco.'
  else if (!/\.(xlsx|csv)$/i.test(archivo.name)) e.archivo = 'Use un archivo Excel (.xlsx) o CSV (.csv).'
  else if (archivo.size > 2 * 1024 * 1024) e.archivo = 'El archivo pesa más de 2 MB: exporta un periodo más corto.'
  const numero = /^-?\d{1,14}([.,]\d{1,2})?$/
  for (const [campo, valor] of [['saldoInicial', saldoInicial], ['saldoFinal', saldoFinal]]) {
    if (String(valor).trim() && !numero.test(String(valor).trim())) e[campo] = 'Un número, con hasta 2 decimales.'
  }
  if (Boolean(String(saldoInicial).trim()) !== Boolean(String(saldoFinal).trim())) e.saldoFinal = e.saldoFinal ?? 'Indique los dos saldos, o ninguno.'
  return e
}

export const MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

/** Año y mes de hoy (el libro se pide por mes completo). */
export function mesActual(hoy = new Date()) {
  return { anio: hoy.getFullYear(), mes: hoy.getMonth() + 1 }
}

/** Los años que se ofrecen: desde 3 años atrás hasta el actual. */
export const aniosDisponibles = (hoy = new Date()) => Array.from({ length: 4 }, (_, i) => hoy.getFullYear() - 3 + i)

/** Nombre claro de un periodo del flujo: «2026-10» → «Octubre 2026»; un día queda como fecha; «vencido» tal cual. */
export function nombreDePeriodo(periodo) {
  if (periodo === 'vencido') return 'Ya vencido'
  const mes = /^(\d{4})-(\d{2})$/.exec(periodo)
  if (mes) return `${MESES[Number(mes[2]) - 1]} ${mes[1]}`
  const dia = /^(\d{4})-(\d{2})-(\d{2})$/.exec(periodo)
  return dia ? `${dia[3]}/${dia[2]}/${dia[1]}` : periodo
}

/** Lo que se puede revisar antes de pedir un reporte por rango. Devuelve el mensaje, o '' si está bien. */
export function revisarRango({ desde, hasta }, hoy) {
  if (!desde || !hasta) return 'Indique desde y hasta.'
  if (desde > hasta) return '«Desde» no puede ser posterior a «Hasta».'
  if ((new Date(hasta) - new Date(desde)) / 86_400_000 > 732) return 'El rango no puede pasar de dos años.'
  if (hoy && hasta > hoy) return '«Hasta» no puede ser una fecha futura.'
  return ''
}

/** ¿El importe llega al límite de bancarización? `umbral` viene del servidor: {PEN: '2000.00', USD: '500.00'}. */
export function superaUmbral(monto, moneda, umbral) {
  const limite = Number(umbral?.[moneda])
  const valor = Number(String(monto ?? '').replace(',', '.'))
  return Number.isFinite(limite) && limite > 0 && Number.isFinite(valor) && valor >= limite
}

export const TONO_ALERTA = { critica: 'rojo', aviso: 'naranja', info: 'azul' }

/** Cuánto pesa un voucher, en texto corto: «340 KB», «1,2 MB». */
export function pesoLegible(bytes) {
  const n = Number(bytes)
  if (!Number.isFinite(n) || n < 0) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`
  return `${(n / (1024 * 1024)).toFixed(1).replace('.', ',')} MB`
}

/** Revisa el voucher antes de subirlo; el servidor vuelve a revisarlo todo. Devuelve el mensaje o ''. */
export function validarVoucher(archivo) {
  if (!archivo) return 'Elija la foto o el PDF.'
  if (!/\.(jpe?g|png|webp|pdf)$/i.test(archivo.name)) return 'Use una foto (JPG, PNG, WEBP) o un PDF.'
  if (archivo.size > 5 * 1024 * 1024) return 'El archivo pesa más de 5 MB.'
  if (archivo.size === 0) return 'El archivo está vacío.'
  return ''
}

/** Total en céntimos de los gastos marcados, devuelto en soles (sin errores de decimales). */
export function totalDeGastos(gastos, marcados) {
  return gastos.filter((g) => marcados.has(g.id)).reduce((suma, g) => suma + Math.round(Number(g.monto) * 100), 0) / 100
}
