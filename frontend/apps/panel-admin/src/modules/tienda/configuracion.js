// Lógica pura de la pantalla «Configuración de la tienda»: del servidor al formulario y de vuelta.

export const MAX_NOMBRE = 80
export const MAX_POCAS = 500
export const MAX_AVISO = 90
export const MAX_PUNTO = 60
export const N_AVISOS = 3
export const N_PUNTOS = 4

/** Campos de texto del contenido de la tienda y su largo máximo (iguales a los del servidor). */
export const TEXTOS = {
  descripcion: 200,
  color_principal: 7,
  whatsapp: 30,
  telefono: 30,
  correo: 150,
  direccion: 250,
  horario: 200,
  mapa_url: 500,
  facebook: 300,
  instagram: 300,
  tiktok: 300,
  youtube: 300,
  portada_etiqueta: 80,
  portada_titulo: 120,
  portada_subtitulo: 250,
  servicio_titulo: 100,
  servicio_texto: 300,
  garantia_texto: 250,
  entrega_texto: 250,
  libro_reclamaciones_url: 500,
  terminos_url: 500,
  privacidad_url: 500,
}
const ENLACES = ['mapa_url', 'facebook', 'instagram', 'tiktok', 'youtube', 'libro_reclamaciones_url', 'terminos_url', 'privacidad_url']
const norm = (t) => String(t ?? '').trim().replace(/\s+/g, ' ')
const casillas = (lista, n) => Array.from({ length: n }, (_, i) => lista?.[i] ?? '')
const sinVacias = (lista) => lista.map(norm).filter(Boolean)

/** Lo que devuelve el servidor → los valores del formulario (todo como texto, listo para escribir). */
export const desdeServidor = (d) => ({
  nombre: d.nombre ?? '',
  lista_precio: d.lista_precio === null || d.lista_precio === undefined ? '' : String(d.lista_precio),
  pocas_unidades: String(d.pocas_unidades ?? 0),
  precios_con_igv: Boolean(d.precios_con_igv),
  almacenes: [...(d.almacenes ?? [])].sort((a, b) => a - b),
  ...Object.fromEntries(Object.keys(TEXTOS).map((c) => [c, d[c] ?? ''])),
  avisos: casillas(d.avisos, N_AVISOS),
  servicio_puntos: casillas(d.servicio_puntos, N_PUNTOS),
  servicio_visible: Boolean(d.servicio_visible),
  nombre_junto_al_logo: d.nombre_junto_al_logo !== false,
})

/** Solo lo que cambió respecto de lo guardado, con el tipo que espera el servidor (la apertura va aparte). */
export function cambiosDeConfiguracion(servidor, form) {
  const base = desdeServidor(servidor)
  const cambios = {}
  if (form.nombre.trim().replace(/\s+/g, ' ') !== base.nombre) cambios.nombre = form.nombre.trim().replace(/\s+/g, ' ')
  if (form.lista_precio !== base.lista_precio) cambios.lista_precio = form.lista_precio === '' ? null : Number(form.lista_precio)
  if (form.pocas_unidades !== base.pocas_unidades && form.pocas_unidades !== '') cambios.pocas_unidades = Number(form.pocas_unidades)
  if (form.precios_con_igv !== base.precios_con_igv) cambios.precios_con_igv = form.precios_con_igv
  const ordenados = [...form.almacenes].sort((a, b) => a - b)
  if (ordenados.join(',') !== base.almacenes.join(',')) cambios.almacenes = ordenados
  for (const campo of Object.keys(TEXTOS)) {
    if (norm(form[campo]) !== norm(base[campo])) cambios[campo] = norm(form[campo])
  }
  for (const campo of ['avisos', 'servicio_puntos']) {
    if (sinVacias(form[campo]).join('|') !== sinVacias(base[campo]).join('|')) cambios[campo] = sinVacias(form[campo])
  }
  if (form.servicio_visible !== base.servicio_visible) cambios.servicio_visible = form.servicio_visible
  if (form.nombre_junto_al_logo !== base.nombre_junto_al_logo) cambios.nombre_junto_al_logo = form.nombre_junto_al_logo
  return cambios
}

/** Revisa en el navegador lo escrito; el servidor valida otra vez. */
export function revisarConfiguracion(form) {
  const e = {}
  const nombre = form.nombre.trim()
  if (!nombre) e.nombre = 'Escribe el nombre de la tienda.'
  else if (nombre.length > MAX_NOMBRE) e.nombre = `El nombre admite hasta ${MAX_NOMBRE} caracteres.`
  if (form.pocas_unidades === '' || !/^\d{1,3}$/.test(form.pocas_unidades) || Number(form.pocas_unidades) > MAX_POCAS) {
    e.pocas_unidades = `Escribe un número entero de 0 a ${MAX_POCAS}.`
  }
  const color = form.color_principal.trim()
  if (color && !/^#[0-9a-fA-F]{6}$/.test(color)) e.color_principal = 'Escribe un color como #E2372A o elígelo del cuadro.'
  const correo = form.correo.trim()
  if (correo && !/^\S+@\S+\.\S+$/.test(correo)) e.correo = 'Escribe un correo válido.'
  for (const campo of ENLACES) {
    const v = form[campo].trim()
    if (v && !/^https?:\/\/\S+$/i.test(v)) e[campo] = 'Escribe el enlace completo, empezando con https://'
  }
  return e
}

/** Los almacenes agrupados por empresa, en el orden en que llegan (ya vienen por empresa). */
export function agruparAlmacenes(almacenes) {
  const grupos = []
  const porEmpresa = new Map()
  for (const a of almacenes) {
    let grupo = porEmpresa.get(a.empresa)
    if (!grupo) {
      grupo = { empresa: a.empresa, almacenes: [] }
      porEmpresa.set(a.empresa, grupo)
      grupos.push(grupo)
    }
    grupo.almacenes.push(a)
  }
  return grupos
}
