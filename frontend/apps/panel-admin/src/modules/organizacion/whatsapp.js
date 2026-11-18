// Lógica pura de la pantalla «WhatsApp Business»: del servidor al formulario y de vuelta.

export const MAX_TOKEN = 600

export const MODOS = {
  APAGADO: { texto: 'Apagado', detalle: 'No se envía nada por WhatsApp. Los avisos salen solo por correo.' },
  PRUEBA: { texto: 'Prueba', detalle: 'Los avisos se registran pero NO se envían. Sirve para probar sin molestar a nadie.' },
  ACTIVO: { texto: 'Activo', detalle: 'Se envía de verdad a tus clientes. Necesita la cuenta y las plantillas listas.' },
}

const norm = (t) => String(t ?? '').trim()

/** Lo que devuelve el servidor → los valores del formulario. El token nunca viene: empieza vacío. */
export const desdeServidor = (d) => ({
  modo: d.modo ?? 'APAGADO',
  numero: d.numero ?? '',
  telefono_id: d.telefono_id ?? '',
  token: '',
  quitar_token: false,
  version_api: d.version_api ?? 'v21.0',
  idioma: d.idioma ?? 'es',
  plantillas: { ...(d.plantillas ?? {}) },
})

/** Solo lo que cambió, con el tipo que espera el servidor. */
export function cambiosDeWhatsApp(servidor, form) {
  const base = desdeServidor(servidor)
  const c = {}
  for (const campo of ['numero', 'telefono_id', 'version_api', 'idioma']) {
    if (norm(form[campo]) !== norm(base[campo])) c[campo] = norm(form[campo])
  }
  if (form.quitar_token) c.quitar_token = true
  else if (norm(form.token)) c.token = norm(form.token)
  const plantillas = {}
  const claves = new Set([...Object.keys(base.plantillas), ...Object.keys(form.plantillas)])
  for (const clave of claves) {
    const nuevo = norm(form.plantillas[clave])
    if (nuevo !== norm(base.plantillas[clave])) plantillas[clave] = nuevo
  }
  if (Object.keys(plantillas).length > 0) c.plantillas = plantillas
  if (form.modo !== base.modo) c.modo = form.modo
  return c
}

/** Revisa en el navegador lo escrito; el servidor valida otra vez. */
export function revisarWhatsApp(form) {
  const e = {}
  if (norm(form.telefono_id) && !/^\d{5,40}$/.test(norm(form.telefono_id))) e.telefono_id = 'El ID del número tiene solo dígitos.'
  if (!/^v\d{1,2}\.\d$/.test(norm(form.version_api))) e.version_api = 'Escribe la versión así: v21.0'
  if (!/^[a-z]{2}(_[A-Z]{2})?$/.test(norm(form.idioma))) e.idioma = 'Escribe el idioma así: es o es_PE'
  for (const [clave, nombre] of Object.entries(form.plantillas)) {
    if (norm(nombre) && !/^[a-z0-9_]{1,80}$/.test(norm(nombre))) {
      e[`plantilla_${clave}`] = 'Solo minúsculas, números y guion bajo (como la nombra Meta).'
    }
  }
  return e
}

/** Los avisos agrupados por módulo (Tienda, Servicio técnico), en el orden en que llegan. */
export function agruparEventos(eventos) {
  const grupos = []
  for (const ev of eventos ?? []) {
    let g = grupos.find((x) => x.modulo === ev.modulo)
    if (!g) {
      g = { modulo: ev.modulo, eventos: [] }
      grupos.push(g)
    }
    g.eventos.push(ev)
  }
  return grupos
}
