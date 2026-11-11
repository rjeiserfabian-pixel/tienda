// Definición de los reportes de inventario y atajos de periodo (pantalla Reportes).

/**
 * Cada reporte declara qué filtros usa: `producto` (Kardex), `almacen` ('obligatorio', 'opcional' o
 * ninguno) y `periodo` ('rango' = desde/hasta, 'fecha' = a un día). La pantalla solo muestra esos.
 */
export const REPORTES = {
  'kardex-fisico': {
    nombre: 'Kardex físico',
    formato: 'Formato 12.1',
    ayuda: 'Entradas, salidas y saldo en unidades de un producto. Es el libro de inventario permanente.',
    icono: 'history',
    producto: true,
    almacen: 'obligatorio',
    periodo: 'rango',
  },
  'kardex-valorizado': {
    nombre: 'Kardex valorizado',
    formato: 'Formato 13.1',
    ayuda: 'Lo mismo con el costo unitario y total de cada movimiento, al promedio ponderado.',
    icono: 'coins',
    producto: true,
    almacen: 'obligatorio',
    periodo: 'rango',
  },
  saldos: {
    nombre: 'Saldos de inventario',
    formato: 'A una fecha',
    ayuda: 'Cuánto hay de cada producto, a qué costo y cuánto vale en total.',
    icono: 'boxes',
    almacen: 'opcional',
    periodo: 'fecha',
  },
  'costo-venta': {
    nombre: 'Costo de venta',
    formato: 'Por producto',
    ayuda: 'Inventario inicial, entradas, salidas e inventario final, con el costo de venta de cada producto.',
    icono: 'chart',
    almacen: 'opcional',
    periodo: 'rango',
  },
  antiguedad: {
    nombre: 'Antigüedad del stock',
    formato: 'Solo Excel',
    ayuda: 'Cuánto de lo que hay lleva mucho tiempo guardado, por tramos de días, para despachar primero lo más antiguo.',
    icono: 'history',
    almacen: 'opcional',
    periodo: 'ninguno',
    filtrosAntiguedad: true,
    soloExcel: true,
  },
  movimientos: {
    nombre: 'Libro de movimientos',
    formato: 'Dcab y Ddet · solo Excel',
    ayuda: 'Todas las entradas y salidas del periodo, para el contador o para otro sistema.',
    icono: 'documento',
    periodo: 'rango',
    soloExcel: true,
  },
}

const iso = (fecha) => fecha.toLocaleDateString('en-CA')
const hoy = () => new Date()
const primerDia = (fecha, meses = 0) => new Date(fecha.getFullYear(), fecha.getMonth() + meses, 1)

/** Atajos de periodo para reportes con rango; cada uno devuelve `{ desde, hasta }` (nunca futuro). */
export const ATAJOS_RANGO = [
  { id: 'mes', texto: 'Este mes', rango: () => ({ desde: iso(primerDia(hoy())), hasta: iso(hoy()) }) },
  { id: 'anterior', texto: 'Mes anterior', rango: () => ({ desde: iso(primerDia(hoy(), -1)), hasta: iso(new Date(hoy().getFullYear(), hoy().getMonth(), 0)) }) },
  { id: 'trimestre', texto: 'Últimos 3 meses', rango: () => ({ desde: iso(primerDia(hoy(), -2)), hasta: iso(hoy()) }) },
  { id: 'anio', texto: 'Año actual', rango: () => ({ desde: iso(new Date(hoy().getFullYear(), 0, 1)), hasta: iso(hoy()) }) },
]

/** Atajos para reportes «a una fecha». */
export const ATAJOS_FECHA = [
  { id: 'hoy', texto: 'Hoy', fecha: () => iso(hoy()) },
  { id: 'mes-anterior', texto: 'Fin del mes anterior', fecha: () => iso(new Date(hoy().getFullYear(), hoy().getMonth(), 0)) },
  { id: 'anio-anterior', texto: 'Fin del año anterior', fecha: () => iso(new Date(hoy().getFullYear() - 1, 11, 31)) },
]

/** Lo último que eligió la persona en esta empresa (reporte y almacén); solo una comodidad. */
const clave = (empresa) => `reportes-inventario:${empresa}`
export function leerPreferencias(empresa) {
  try {
    const guardado = JSON.parse(localStorage.getItem(clave(empresa)) ?? '{}')
    return { tipo: guardado.tipo in REPORTES ? guardado.tipo : 'kardex-fisico', almacen: typeof guardado.almacen === 'string' ? guardado.almacen : '' }
  } catch {
    return { tipo: 'kardex-fisico', almacen: '' }
  }
}
export function guardarPreferencias(empresa, valores) {
  try {
    localStorage.setItem(clave(empresa), JSON.stringify(valores))
  } catch {
    /* sin almacenamiento: no pasa nada */
  }
}
