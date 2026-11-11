// Datos y formatos de RR.HH.: textos de los catálogos y cómo se muestran los valores legales.

export const AFPS = [
  ['HABITAT', 'AFP Habitat'],
  ['INTEGRA', 'AFP Integra'],
  ['PRIMA', 'Prima AFP'],
  ['PROFUTURO', 'Profuturo AFP'],
]

export const CODIGOS_PARAMETRO = [
  ['RMV', 'Remuneración mínima vital (RMV)'],
  ['UIT', 'Unidad impositiva tributaria (UIT)'],
  ['ASIGNACION_FAMILIAR', 'Asignación familiar (% de la RMV)'],
  ['ONP', 'ONP (% de la remuneración)'],
  ['REM_MAX_ASEGURABLE', 'Remuneración máxima asegurable (AFP)'],
  ['BONIF_EXTRAORDINARIA', 'Bonificación extraordinaria (%)'],
  ['DIAS_MES', 'Días del mes para el valor del día'],
  ['HORAS_JORNADA', 'Horas de la jornada diaria'],
  ['HORAS_HE_PRIMERAS', 'Horas extra de cada día con la primera sobretasa'],
  ['SOBRETASA_HE_PRIMERAS', 'Sobretasa de las primeras horas extra (%)'],
  ['SOBRETASA_HE_SIGUIENTES', 'Sobretasa de las siguientes horas extra (%)'],
  ['SOBRETASA_FERIADO', 'Sobretasa del trabajo en feriado (%)'],
  ['DEDUCCION_RENTA5_UIT', 'Deducción de renta de 5.ª categoría (UIT)'],
]

export const CATEGORIAS_ASISTENCIA = [
  ['LABORADO', 'Día laborado'],
  ['DESCANSO_SEMANAL', 'Descanso semanal'],
  ['FALTA', 'Falta o permiso sin goce'],
  ['DESCANSO_PAGADO', 'Descanso pagado'],
  ['DESCANSO_MEDICO', 'Descanso médico'],
  ['VACACIONES', 'Vacaciones'],
  ['FERIADO', 'Feriado'],
  ['TRABAJO_FERIADO', 'Trabajo en feriado o descanso'],
  ['OTRO', 'Otro'],
]

export const TIPOS_CONCEPTO = [
  ['INGRESO', 'Ingreso'],
  ['DESCUENTO', 'Descuento al trabajador'],
  ['APORTE_EMPLEADOR', 'Aporte del empleador'],
]

const NUMERO = new Intl.NumberFormat('es-PE', { maximumFractionDigits: 4 })
const SOLES = new Intl.NumberFormat('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** Texto del servidor («1130.0000») → «1,130.0000» sin ceros de más: «1,130». */
export const numero = (valor) => {
  const n = Number(valor)
  return valor === null || valor === undefined || valor === '' || !Number.isFinite(n) ? '—' : NUMERO.format(n)
}

export const soles = (valor) => {
  const n = Number(valor)
  return valor === null || valor === undefined || valor === '' || !Number.isFinite(n) ? '—' : `S/ ${SOLES.format(n)}`
}

/** Un parámetro según su unidad: S/ 1,130.00, 13 % o 30. */
export const valorDeParametro = (valor, unidad) => {
  if (unidad === 'SOLES') return soles(valor)
  if (unidad === 'PORCENTAJE') return `${numero(valor)} %`
  return numero(valor)
}

/** Fecha AAAA-MM-DD → 28/10/2026 (sin pasar por zonas horarias). */
export const fechaCorta = (iso) => {
  if (!iso) return '—'
  const [a, m, d] = String(iso).slice(0, 10).split('-')
  return a && m && d ? `${d}/${m}/${a}` : '—'
}

/** Lo escrito en un campo decimal: coma o punto, solo dígitos («1,5» → «1.5»). */
export const decimal = (texto) => texto.replace(',', '.').replace(/[^0-9.]/g, '')
export const entero = (texto) => texto.replace(/\D/g, '')
export const enMayusculas = (texto) => texto.toUpperCase().replace(/[^A-Z0-9_]/g, '')

/** ¿Es un decimal válido, mayor o igual que 0 (y a lo sumo `maximo`)? */
export const decimalValido = (texto, maximo = Infinity) => {
  const t = String(texto ?? '').trim()
  return /^\d+(\.\d+)?$/.test(t) && Number(t) <= maximo
}

export const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']

/** Fecha del servidor (AAAA-MM-DD) → «marzo 2026». */
export const mesAnio = (iso) => (iso ? `${MESES[Number(String(iso).slice(5, 7)) - 1]} ${String(iso).slice(0, 4)}` : '—')
