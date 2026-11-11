// Lógica pura de las especificaciones técnicas por categoría: la plantilla de campos (editor) y los
// valores de cada producto. El servidor valida todo otra vez; aquí solo se arma y se revisa lo básico.

export const TIPOS_CAMPO = [
  ['TEXTO', 'Texto'],
  ['NUMERO', 'Número'],
  ['LISTA', 'Lista de opciones'],
  ['SI_NO', 'Sí o no'],
]
export const NOMBRE_TIPO = Object.fromEntries(TIPOS_CAMPO)
export const SECCION_INICIAL = 'General'
export const MAX_CAMPOS = 80
export const MAX_OPCIONES = 40

let contador = 0
/** Identificador local estable para las listas editables (no es el id del servidor). */
export const nuevoUid = () => `campo-${(contador += 1)}`

export const campoVacio = (seccion = SECCION_INICIAL) => ({
  uid: nuevoUid(),
  id: null,
  nombre: '',
  tipo: 'TEXTO',
  unidad: '',
  opciones: [],
  seccion,
  es_filtro: false,
  en_tarjeta: false,
  quitado: false,
})

/** Campo que viene del servidor, listo para editarse. Los desactivados salen como «quitados». */
export const desdeServidor = (c) => ({
  uid: nuevoUid(),
  id: c.id,
  nombre: c.nombre,
  tipo: c.tipo,
  unidad: c.unidad ?? '',
  opciones: Array.isArray(c.opciones) ? [...c.opciones] : [],
  seccion: c.seccion || SECCION_INICIAL,
  es_filtro: Boolean(c.es_filtro),
  en_tarjeta: Boolean(c.en_tarjeta),
  quitado: c.estado === 'INACTIVO',
})

/** Cuerpo del POST: la lista completa de campos vigentes, en el orden en que se muestran. */
export const cuerpoDeCampos = (campos) => ({
  campos: campos
    .filter((c) => !c.quitado)
    .map((c) => ({
      ...(c.id ? { id: c.id } : {}),
      nombre: c.nombre.trim(),
      tipo: c.tipo,
      unidad: c.tipo === 'NUMERO' ? c.unidad.trim() : '',
      opciones: c.tipo === 'LISTA' ? c.opciones : [],
      seccion: c.seccion.trim() || SECCION_INICIAL,
      es_filtro: c.tipo !== 'TEXTO' && c.es_filtro,
      en_tarjeta: c.en_tarjeta,
    })),
})

/** Secciones en el orden de su primer campo: [{seccion, campos: [...]}]. */
export function agruparPorSeccion(campos) {
  const grupos = new Map()
  for (const c of campos) {
    const clave = c.seccion.trim() || SECCION_INICIAL
    if (!grupos.has(clave)) grupos.set(clave, [])
    grupos.get(clave).push(c)
  }
  return [...grupos.entries()].map(([seccion, lista]) => ({ seccion, campos: lista }))
}

/** Sube o baja un campo dentro de su sección (intercambia con el vecino de la misma sección). */
export function moverCampo(campos, uid, sentido) {
  const posicion = campos.findIndex((c) => c.uid === uid)
  if (posicion < 0) return campos
  const seccion = (campos[posicion].seccion.trim() || SECCION_INICIAL)
  let vecino = posicion + sentido
  while (vecino >= 0 && vecino < campos.length) {
    const candidato = campos[vecino]
    if (!candidato.quitado && (candidato.seccion.trim() || SECCION_INICIAL) === seccion) break
    vecino += sentido
  }
  if (vecino < 0 || vecino >= campos.length) return campos
  const copia = [...campos]
  ;[copia[posicion], copia[vecino]] = [copia[vecino], copia[posicion]]
  return copia
}

/** Sube o baja una sección completa; los campos quitados quedan al final. */
export function moverSeccion(campos, seccion, sentido) {
  const vigentes = campos.filter((c) => !c.quitado)
  const grupos = agruparPorSeccion(vigentes)
  const i = grupos.findIndex((g) => g.seccion === seccion)
  const j = i + sentido
  if (i < 0 || j < 0 || j >= grupos.length) return campos
  ;[grupos[i], grupos[j]] = [grupos[j], grupos[i]]
  return [...grupos.flatMap((g) => g.campos), ...campos.filter((c) => c.quitado)]
}

/** Revisa la lista antes de enviarla; devuelve {uid: mensaje} y un mensaje general. */
export function revisarCampos(campos) {
  const errores = {}
  const vistos = new Map()
  const vigentes = campos.filter((c) => !c.quitado)
  if (vigentes.length > MAX_CAMPOS) return { general: `Una categoría admite hasta ${MAX_CAMPOS} campos.`, porCampo: {} }
  for (const c of vigentes) {
    const nombre = c.nombre.trim()
    if (!nombre) errores[c.uid] = 'Escribe el nombre del dato.'
    else if (vistos.has(nombre.toLowerCase())) errores[c.uid] = 'Ya hay otro dato con este nombre.'
    else vistos.set(nombre.toLowerCase(), c.uid)
    if (c.tipo === 'LISTA' && c.opciones.length > MAX_OPCIONES) errores[c.uid] = `Una lista admite hasta ${MAX_OPCIONES} opciones.`
  }
  return { general: Object.keys(errores).length ? 'Revisa los datos marcados en rojo.' : '', porCampo: errores }
}

/** Separa lo que se pega o escribe en opciones limpias, sin repetir las que ya hay. */
export function sumarOpciones(actuales, texto) {
  const vistas = new Set(actuales.map((o) => o.toLowerCase()))
  const nuevas = []
  for (const trozo of String(texto).split(/[\n,;]+/)) {
    const opcion = trozo.replace(/\s+/g, ' ').trim().slice(0, 60)
    if (opcion && !vistas.has(opcion.toLowerCase())) {
      vistas.add(opcion.toLowerCase())
      nuevas.push(opcion)
    }
  }
  return [...actuales, ...nuevas]
}

// ---------------------------------------------------------------------------
// Valores de un producto
// ---------------------------------------------------------------------------
const NUMERO = /^\d+([.,]\d{1,3})?$/

export const campoActivo = (c) => c.estado === 'ACTIVO'

/** Los valores como los pide el servidor: solo campos vigentes y sin vacíos. */
export function valoresParaEnviar(camposActivos, valores) {
  const salida = {}
  for (const c of camposActivos) {
    const v = valores?.[c.clave]
    if (c.tipo === 'SI_NO') {
      if (typeof v === 'boolean') salida[c.clave] = v
    } else if (v !== undefined && v !== null && String(v).trim() !== '') {
      salida[c.clave] = String(v).trim()
    }
  }
  return salida
}

/** Revisión rápida de los valores (números y listas); el servidor valida de nuevo. */
export function revisarValores(camposActivos, valores) {
  const errores = {}
  for (const c of camposActivos) {
    const v = valores?.[c.clave]
    if (v === undefined || v === null || String(v).trim() === '') continue
    if (c.tipo === 'NUMERO' && !NUMERO.test(String(v).trim())) errores[c.clave] = 'Escribe un número (hasta 3 decimales).'
    if (c.tipo === 'LISTA' && c.opciones.length && !c.opciones.includes(String(v))) errores[c.clave] = 'Elige una de las opciones.'
  }
  return errores
}

/** Cuántos valores guardados ya no pertenecen a ningún campo vigente de la categoría. */
export function valoresHuerfanos(camposActivos, valores) {
  const claves = new Set(camposActivos.map((c) => c.clave))
  return Object.entries(valores ?? {}).filter(([k, v]) => !claves.has(k) && v !== '' && v !== null && v !== undefined).length
}

/** Errores por dato que devuelve el servidor: detalle.especificaciones = {clave: mensaje}. */
export function erroresDeEspecificaciones(error) {
  const detalle = error?.response?.data?.error?.detalle?.especificaciones
  if (!detalle) return {}
  if (typeof detalle === 'string') return { _general: detalle }
  if (Array.isArray(detalle)) return { _general: detalle.join(' ') }
  return Object.fromEntries(
    Object.entries(detalle).map(([clave, m]) => [clave, Array.isArray(m) ? m.join(' ') : String(m)]),
  )
}
