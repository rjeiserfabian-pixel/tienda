// Definición de los catálogos de RR.HH. Las pantallas de lista, alta y ficha son las mismas de Mantenimiento
// (MaestroListado y MaestroFicha): aquí solo cambian los campos y las columnas.
import ResumenParametros from './components/ResumenParametros'
import { AFPS, CATEGORIAS_ASISTENCIA, CODIGOS_PARAMETRO, decimal, decimalValido, enMayusculas, entero, fechaCorta, numero, soles, TIPOS_CONCEPTO, valorDeParametro } from './rrhh'

const ESTADOS = [
  ['ACTIVO', 'Activo'],
  ['INACTIVO', 'Inactivo'],
]
const ESTADO = { nombre: 'estado', etiqueta: 'Estado', icono: 'settings', tipo: 'select', opciones: ESTADOS, soloEdicion: true }
const siNo = (valor) => (valor ? <span className="pildora" data-tono="verde">Sí</span> : <span className="celda-suave">No</span>)
const etiqueta = (lista, valor) => lista.find(([v]) => v === valor)?.[1] ?? valor

const BASE = { deOrganizacion: true, filtros: [] }
const PERMISO = 'RRHH.PARAMETROS'

export const REGIMENES = {
  ...BASE,
  clave: 'rrhh-regimenes',
  ruta: '/rrhh/regimenes',
  endpoint: '/rrhh/regimenes/',
  permiso: PERMISO,
  icono: 'building',
  titulo: 'Regímenes laborales',
  singular: 'régimen laboral',
  descripcion: 'Las reglas de cada régimen: EsSalud, días de vacaciones y cuánto son las gratificaciones y la CTS. Cada contrato elige el suyo.',
  buscar: 'Buscar régimen…',
  sembrar: { texto: 'Cargar general y pequeña empresa', exito: (n) => (n ? `Se cargaron ${n} regímenes.` : 'Ya tienes los regímenes base.') },
  tituloFila: (r) => r.nombre,
  subtituloFila: (r) => r.codigo,
  inicial: { codigo: '', nombre: '', tasa_essalud: '9', dias_vacaciones: '30', factor_gratificacion: '1', factor_cts: '1', estado: 'ACTIVO' },
  columnas: [
    { titulo: 'Régimen', celda: (r) => (<><strong>{r.nombre}</strong><br /><small className="celda-suave">{r.codigo}</small></>) },
    { titulo: 'EsSalud', celda: (r) => `${numero(r.tasa_essalud)} %` },
    { titulo: 'Vacaciones', celda: (r) => `${r.dias_vacaciones} días` },
    { titulo: 'Gratificación', suave: true, celda: (r) => `${numero(r.factor_gratificacion)} sueldo(s)` },
    { titulo: 'CTS al año', suave: true, celda: (r) => `${numero(r.factor_cts)} sueldo(s)` },
  ],
  campos: [
    { nombre: 'codigo', etiqueta: 'Código', icono: 'documento', requerido: true, placeholder: 'Ej. PEQUENA', maxLength: 20, transformar: enMayusculas },
    { nombre: 'nombre', etiqueta: 'Nombre', icono: 'building', requerido: true, placeholder: 'Ej. Pequeña empresa (MYPE)', maxLength: 80 },
    { nombre: 'tasa_essalud', etiqueta: 'EsSalud del empleador (%)', icono: 'shield', requerido: true, maxLength: 6, transformar: decimal, ayuda: 'Lo que aporta la empresa sobre la remuneración.' },
    { nombre: 'dias_vacaciones', etiqueta: 'Días de vacaciones al año', icono: 'calendario', requerido: true, maxLength: 2, transformar: entero },
    { nombre: 'factor_gratificacion', etiqueta: 'Sueldos por gratificación', icono: 'coins', requerido: true, maxLength: 4, transformar: decimal, ayuda: 'Cada gratificación (julio y diciembre): 1 sueldo, medio sueldo (0.5)…' },
    { nombre: 'factor_cts', etiqueta: 'Sueldos de CTS al año', icono: 'coins', requerido: true, maxLength: 4, transformar: decimal, ayuda: 'Cuánto sueldo es la CTS de un año completo.' },
    ESTADO,
  ],
  validar: (f) => {
    const e = {}
    if (!String(f.codigo ?? '').trim()) e.codigo = 'Ingrese el código.'
    if (!String(f.nombre ?? '').trim()) e.nombre = 'Ingrese el nombre del régimen.'
    if (!decimalValido(f.tasa_essalud, 100)) e.tasa_essalud = 'Un porcentaje de 0 a 100.'
    if (!/^\d{1,2}$/.test(String(f.dias_vacaciones ?? '')) || Number(f.dias_vacaciones) < 1 || Number(f.dias_vacaciones) > 60) e.dias_vacaciones = 'Entre 1 y 60 días.'
    if (!decimalValido(f.factor_gratificacion, 3)) e.factor_gratificacion = 'Entre 0 y 3 sueldos.'
    if (!decimalValido(f.factor_cts, 3)) e.factor_cts = 'Entre 0 y 3 sueldos.'
    return e
  },
}

export const PARAMETROS = {
  ...BASE,
  femenino: false,
  clave: 'rrhh-parametros',
  ruta: '/rrhh/parametros',
  endpoint: '/rrhh/parametros/',
  permiso: PERMISO,
  icono: 'coins',
  titulo: 'Valores legales',
  singular: 'parámetro',
  descripcion: 'Sueldo mínimo, UIT, ONP y demás valores de la ley. Cada valor rige desde una fecha: cuando cambia, registra el nuevo con su fecha y la planilla de cada mes usa el que le correspondía.',
  buscar: 'Buscar parámetro…',
  arriba: ResumenParametros,
  tituloFila: (r) => r.codigo_nombre,
  subtituloFila: (r) => `Desde ${fechaCorta(r.vigente_desde)}`,
  inicial: { codigo: '', valor: '', vigente_desde: '', nota: '', estado: 'ACTIVO' },
  filtros: [{ nombre: 'codigo', todos: 'Todos los parámetros', opciones: CODIGOS_PARAMETRO }],
  columnas: [
    { titulo: 'Parámetro', celda: (r) => <strong>{r.codigo_nombre}</strong> },
    { titulo: 'Valor', celda: (r) => valorDeParametro(r.valor, r.unidad) },
    { titulo: 'Rige desde', celda: (r) => fechaCorta(r.vigente_desde) },
    { titulo: 'Nota', suave: true, celda: (r) => r.nota || '—' },
  ],
  campos: [
    { nombre: 'codigo', etiqueta: 'Parámetro', icono: 'coins', tipo: 'select', opciones: CODIGOS_PARAMETRO, vacio: 'Elija el parámetro', soloAlta: true, completo: true, requerido: true },
    { nombre: 'valor', etiqueta: 'Valor', icono: 'calculator', requerido: true, maxLength: 12, transformar: decimal, ayuda: 'Solo el número: 1130, 13, 5500…' },
    { nombre: 'vigente_desde', etiqueta: 'Rige desde', icono: 'calendario', tipo: 'date', requerido: true },
    { nombre: 'nota', etiqueta: 'De dónde sale', icono: 'documento', maxLength: 200, completo: true, placeholder: 'Ej. Decreto Supremo, resolución de la SBS…' },
    ESTADO,
  ],
  validar: (f) => {
    const e = {}
    if (!f.codigo && f.codigo !== undefined) e.codigo = 'Elija el parámetro.'
    if (!decimalValido(f.valor)) e.valor = 'Escriba un número desde 0.'
    if (!f.vigente_desde) e.vigente_desde = 'Indique desde cuándo rige.'
    return e
  },
}

export const TASAS_AFP = {
  ...BASE,
  clave: 'rrhh-tasas-afp',
  ruta: '/rrhh/tasas-afp',
  endpoint: '/rrhh/tasas-afp/',
  permiso: PERMISO,
  icono: 'shield',
  titulo: 'Tasas de AFP',
  singular: 'tasa de AFP',
  femenino: true,
  descripcion: 'Aporte, prima de seguro y comisiones de cada AFP. La SBS las actualiza cada cierto tiempo: registra las nuevas con su fecha de vigencia.',
  buscar: 'Buscar AFP…',
  tituloFila: (r) => r.afp_nombre,
  subtituloFila: (r) => `Desde ${fechaCorta(r.vigente_desde)}`,
  inicial: { afp: '', vigente_desde: '', aporte_obligatorio: '', prima_seguro: '', comision_flujo: '', comision_mixta: '', remuneracion_maxima_asegurable: '', nota: '', estado: 'ACTIVO' },
  filtros: [{ nombre: 'afp', todos: 'Todas las AFP', opciones: AFPS }],
  columnas: [
    { titulo: 'AFP', celda: (r) => <strong>{r.afp_nombre}</strong> },
    { titulo: 'Rige desde', celda: (r) => fechaCorta(r.vigente_desde) },
    { titulo: 'Aporte', celda: (r) => `${numero(r.aporte_obligatorio)} %` },
    { titulo: 'Prima', celda: (r) => `${numero(r.prima_seguro)} %` },
    { titulo: 'Comisión flujo / mixta', suave: true, celda: (r) => `${numero(r.comision_flujo)} % / ${numero(r.comision_mixta)} %` },
    { titulo: 'Rem. máx. asegurable', suave: true, celda: (r) => soles(r.remuneracion_maxima_asegurable) },
  ],
  campos: [
    { nombre: 'afp', etiqueta: 'AFP', icono: 'shield', tipo: 'select', opciones: AFPS, vacio: 'Elija la AFP', soloAlta: true, requerido: true },
    { nombre: 'vigente_desde', etiqueta: 'Rige desde', icono: 'calendario', tipo: 'date', requerido: true },
    { nombre: 'aporte_obligatorio', etiqueta: 'Aporte obligatorio (%)', icono: 'calculator', requerido: true, maxLength: 6, transformar: decimal },
    { nombre: 'prima_seguro', etiqueta: 'Prima de seguro (%)', icono: 'calculator', requerido: true, maxLength: 6, transformar: decimal },
    { nombre: 'comision_flujo', etiqueta: 'Comisión sobre flujo (%)', icono: 'calculator', requerido: true, maxLength: 6, transformar: decimal },
    { nombre: 'comision_mixta', etiqueta: 'Comisión mixta (%)', icono: 'calculator', requerido: true, maxLength: 6, transformar: decimal },
    { nombre: 'remuneracion_maxima_asegurable', etiqueta: 'Remuneración máxima asegurable (S/)', icono: 'coins', requerido: true, maxLength: 12, transformar: decimal, completo: true, ayuda: 'El tope sobre el que se cobra la prima de seguro.' },
    { nombre: 'nota', etiqueta: 'De dónde sale', icono: 'documento', maxLength: 200, completo: true, placeholder: 'Ej. Circular de la SBS' },
    ESTADO,
  ],
  validar: (f) => {
    const e = {}
    if (!f.afp && f.afp !== undefined) e.afp = 'Elija la AFP.'
    if (!f.vigente_desde) e.vigente_desde = 'Indique desde cuándo rigen.'
    for (const campo of ['aporte_obligatorio', 'prima_seguro', 'comision_flujo', 'comision_mixta']) {
      if (!decimalValido(f[campo], 100)) e[campo] = 'Un porcentaje de 0 a 100.'
    }
    if (!decimalValido(f.remuneracion_maxima_asegurable)) e.remuneracion_maxima_asegurable = 'Escriba un monto desde 0.'
    return e
  },
}

export const TIPOS_ASISTENCIA = {
  ...BASE,
  clave: 'rrhh-tipos-asistencia',
  ruta: '/rrhh/tipos-asistencia',
  endpoint: '/rrhh/tipos-asistencia/',
  permiso: PERMISO,
  icono: 'checklist',
  titulo: 'Tipos de asistencia',
  singular: 'tipo de asistencia',
  descripcion: 'Los códigos que se marcan cada día (A, F, DS, V…) y cómo cuenta cada uno en la planilla.',
  buscar: 'Buscar tipo…',
  sembrar: { texto: 'Cargar los 9 de la hoja', exito: (n) => (n ? `Se cargaron ${n} tipos.` : 'Ya tienes todos los tipos base.') },
  tituloFila: (r) => `${r.codigo} · ${r.nombre}`,
  subtituloFila: (r) => r.categoria_nombre,
  inicial: { codigo: '', nombre: '', categoria: 'LABORADO', se_paga: 'true', cuenta_dia_laborado: 'false', estado: 'ACTIVO' },
  filtros: [{ nombre: 'categoria', todos: 'Todas las categorías', opciones: CATEGORIAS_ASISTENCIA }],
  columnas: [
    { titulo: 'Código', celda: (r) => <strong>{r.codigo}</strong> },
    { titulo: 'Nombre', celda: (r) => r.nombre },
    { titulo: 'Cuenta como', suave: true, celda: (r) => etiqueta(CATEGORIAS_ASISTENCIA, r.categoria) },
    { titulo: 'Se paga', celda: (r) => siNo(r.se_paga) },
    { titulo: 'Día trabajado', celda: (r) => siNo(r.cuenta_dia_laborado) },
  ],
  campos: [
    { nombre: 'codigo', etiqueta: 'Código', icono: 'documento', requerido: true, placeholder: 'Ej. A', maxLength: 6, transformar: enMayusculas },
    { nombre: 'nombre', etiqueta: 'Nombre', icono: 'checklist', requerido: true, placeholder: 'Ej. Asistió', maxLength: 60 },
    { nombre: 'categoria', etiqueta: 'Cuenta en la planilla como', icono: 'calculator', tipo: 'select', opciones: CATEGORIAS_ASISTENCIA, completo: true, ayuda: 'La planilla se guía por esto, no por el código.' },
    { nombre: 'se_paga', etiqueta: 'Se paga el día', icono: 'coins', tipo: 'booleano' },
    { nombre: 'cuenta_dia_laborado', etiqueta: 'Cuenta como día trabajado', icono: 'checklist', tipo: 'booleano', ayuda: 'Cuenta para las horas trabajadas.' },
    ESTADO,
  ],
  validar: (f) => {
    const e = {}
    if (!String(f.codigo ?? '').trim()) e.codigo = 'Ingrese el código.'
    if (!String(f.nombre ?? '').trim()) e.nombre = 'Ingrese el nombre.'
    return e
  },
}

export const FERIADOS = {
  ...BASE,
  clave: 'rrhh-feriados',
  ruta: '/rrhh/feriados',
  endpoint: '/rrhh/feriados/',
  permiso: PERMISO,
  icono: 'calendario',
  titulo: 'Feriados',
  singular: 'feriado',
  descripcion: 'Los días feriados del calendario: en la asistencia se marcan solos y en la planilla se pagan o recargan según corresponda.',
  buscar: 'Buscar feriado…',
  tituloFila: (r) => r.nombre,
  subtituloFila: (r) => fechaCorta(r.fecha),
  inicial: { fecha: '', nombre: '', estado: 'ACTIVO' },
  columnas: [
    { titulo: 'Fecha', celda: (r) => <strong>{fechaCorta(r.fecha)}</strong> },
    { titulo: 'Feriado', celda: (r) => r.nombre },
  ],
  campos: [
    { nombre: 'fecha', etiqueta: 'Fecha', icono: 'calendario', tipo: 'date', requerido: true },
    { nombre: 'nombre', etiqueta: 'Nombre', icono: 'calendario', requerido: true, placeholder: 'Ej. Fiestas Patrias', maxLength: 80 },
    ESTADO,
  ],
  validar: (f) => {
    const e = {}
    if (!f.fecha) e.fecha = 'Indique la fecha.'
    if (!String(f.nombre ?? '').trim()) e.nombre = 'Ingrese el nombre del feriado.'
    return e
  },
}

export const CONCEPTOS = {
  ...BASE,
  clave: 'rrhh-conceptos',
  ruta: '/rrhh/conceptos',
  endpoint: '/rrhh/conceptos/',
  permiso: PERMISO,
  icono: 'calculator',
  titulo: 'Conceptos de planilla',
  singular: 'concepto',
  descripcion: 'Los ingresos, descuentos y aportes que aparecen en la planilla y la boleta, y sobre qué están afectos. El contador completa el código PLAME.',
  buscar: 'Buscar concepto…',
  sembrar: { texto: 'Cargar los conceptos base', exito: (n) => (n ? `Se cargaron ${n} conceptos.` : 'Ya tienes todos los conceptos base.') },
  protegido: (r) => r.es_del_sistema,
  tituloFila: (r) => r.nombre,
  subtituloFila: (r) => r.tipo_nombre,
  inicial: { codigo: '', nombre: '', tipo: 'INGRESO', afecto_pension: 'false', afecto_essalud: 'false', afecto_renta5: 'false', codigo_plame: '', orden: '100', estado: 'ACTIVO' },
  filtros: [{ nombre: 'tipo', todos: 'Todos los tipos', opciones: TIPOS_CONCEPTO }],
  columnas: [
    { titulo: 'Concepto', celda: (r) => (<><strong>{r.nombre}</strong><br /><small className="celda-suave">{r.codigo}{r.es_del_sistema ? ' · del sistema' : ''}</small></>) },
    { titulo: 'Tipo', suave: true, celda: (r) => etiqueta(TIPOS_CONCEPTO, r.tipo) },
    { titulo: 'AFP/ONP', celda: (r) => siNo(r.afecto_pension) },
    { titulo: 'EsSalud', celda: (r) => siNo(r.afecto_essalud) },
    { titulo: 'Renta 5.ª', celda: (r) => siNo(r.afecto_renta5) },
    { titulo: 'Código PLAME', suave: true, celda: (r) => r.codigo_plame || '—' },
  ],
  campos: [
    { nombre: 'codigo', etiqueta: 'Código', icono: 'documento', requerido: true, placeholder: 'Ej. BONO_PUNTUALIDAD', maxLength: 30, transformar: enMayusculas, ayuda: 'En los conceptos del sistema no se cambia.' },
    { nombre: 'nombre', etiqueta: 'Nombre', icono: 'calculator', requerido: true, placeholder: 'Ej. Bono de puntualidad', maxLength: 100 },
    { nombre: 'tipo', etiqueta: 'Tipo', icono: 'calculator', tipo: 'select', opciones: TIPOS_CONCEPTO, soloAlta: true, completo: true },
    { nombre: 'afecto_pension', etiqueta: 'Afecto a AFP/ONP', icono: 'shield', tipo: 'booleano', ayuda: 'Entra en la base del descuento de pensiones.' },
    { nombre: 'afecto_essalud', etiqueta: 'Afecto a EsSalud', icono: 'shield', tipo: 'booleano' },
    { nombre: 'afecto_renta5', etiqueta: 'Afecto a renta de 5.ª', icono: 'shield', tipo: 'booleano' },
    { nombre: 'codigo_plame', etiqueta: 'Código PLAME', icono: 'documento', maxLength: 10, transformar: entero, ayuda: 'Lo completa el contador.' },
    { nombre: 'orden', etiqueta: 'Orden en la boleta', icono: 'ordenar', maxLength: 3, transformar: entero },
    ESTADO,
  ],
  validar: (f) => {
    const e = {}
    if (!String(f.codigo ?? '').trim()) e.codigo = 'Ingrese el código.'
    if (!String(f.nombre ?? '').trim()) e.nombre = 'Ingrese el nombre del concepto.'
    return e
  },
}

export const TRAMOS_RENTA5 = {
  ...BASE,
  clave: 'rrhh-tramos-renta5',
  ruta: '/rrhh/tramos-renta5',
  endpoint: '/rrhh/tramos-renta5/',
  permiso: PERMISO,
  icono: 'coins',
  titulo: 'Tramos de renta de 5.ª',
  singular: 'tramo de renta de 5.ª',
  descripcion: 'La escala del impuesto a la renta de 5.ª categoría: hasta cuántas UIT llega cada tramo y la tasa que se aplica en él. Carga todos los tramos de una escala con la misma fecha de vigencia; el último no lleva tope.',
  tituloFila: (r) => `Tramo ${r.orden}`,
  subtituloFila: (r) => `Desde ${fechaCorta(r.vigente_desde)}`,
  inicial: { vigente_desde: '', orden: '', hasta_uit: '', tasa: '', estado: 'ACTIVO' },
  columnas: [
    { titulo: 'Rige desde', celda: (r) => <strong>{fechaCorta(r.vigente_desde)}</strong> },
    { titulo: 'Tramo', celda: (r) => r.orden },
    { titulo: 'Hasta', celda: (r) => (r.hasta_uit === null ? 'Sin tope (el resto)' : `${numero(r.hasta_uit)} UIT`) },
    { titulo: 'Tasa', celda: (r) => `${numero(r.tasa)} %` },
  ],
  campos: [
    { nombre: 'vigente_desde', etiqueta: 'Rige desde', icono: 'calendario', tipo: 'date', requerido: true },
    { nombre: 'orden', etiqueta: 'N° de tramo', icono: 'ordenar', requerido: true, maxLength: 2, transformar: entero, ayuda: '1 es el primero (el de menor renta).' },
    { nombre: 'hasta_uit', etiqueta: 'Hasta cuántas UIT', icono: 'calculator', maxLength: 8, transformar: decimal, ayuda: 'Déjalo vacío en el último tramo (sin tope).' },
    { nombre: 'tasa', etiqueta: 'Tasa (%)', icono: 'calculator', requerido: true, maxLength: 6, transformar: decimal },
    ESTADO,
  ],
  validar: (f) => {
    const e = {}
    if (!f.vigente_desde) e.vigente_desde = 'Indique desde cuándo rige.'
    if (!/^\d{1,2}$/.test(String(f.orden ?? '')) || Number(f.orden) < 1 || Number(f.orden) > 20) e.orden = 'Entre 1 y 20.'
    if (String(f.hasta_uit ?? '').trim() && (!decimalValido(f.hasta_uit) || Number(f.hasta_uit) <= 0)) e.hasta_uit = 'Un número mayor que cero, o vacío en el último tramo.'
    if (!decimalValido(f.tasa, 100)) e.tasa = 'Un porcentaje de 0 a 100.'
    return e
  },
}

export const CATALOGOS_RRHH = [REGIMENES, PARAMETROS, TASAS_AFP, TRAMOS_RENTA5, TIPOS_ASISTENCIA, FERIADOS, CONCEPTOS]
