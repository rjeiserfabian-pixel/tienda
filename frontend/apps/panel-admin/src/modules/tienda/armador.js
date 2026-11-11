// Lógica pura de la pantalla «Arma tu PC»: del servidor al formulario y de vuelta.

export const MAX_UNIDADES = 10

/** Lo que devuelve el servidor → los valores del formulario. */
export const desdeServidor = (d) => ({
  activo: Boolean(d.activo),
  espacios: d.espacios.map((e) => ({
    clave: e.clave,
    categorias: [...e.categorias],
    obligatorio: Boolean(e.obligatorio),
    max_unidades: String(e.max_unidades),
  })),
  reglas: Object.fromEntries(
    d.reglas.map((r) => [
      r.id,
      { activa: Boolean(r.activa), claves: Object.fromEntries(Object.entries(r.claves).map(([alias, c]) => [alias, c.clave])) },
    ]),
  ),
})

const cuerpoEspacios = (form) =>
  form.espacios.map((e) => ({
    clave: e.clave,
    categorias: e.categorias,
    obligatorio: e.obligatorio,
    max_unidades: Number(e.max_unidades),
  }))

/** Solo se mandan las claves distintas de las de fábrica. */
const cuerpoReglas = (servidor, form) =>
  Object.fromEntries(
    servidor.reglas.map((r) => {
      const actual = form.reglas[r.id]
      const claves = {}
      for (const [alias, c] of Object.entries(r.claves)) {
        if (actual.claves[alias] !== c.defecto) claves[alias] = actual.claves[alias]
      }
      return [r.id, { activa: actual.activa, claves }]
    }),
  )

/** Solo lo que cambió, con el tipo que espera el servidor. */
export function cambiosDelArmador(servidor, form) {
  const base = desdeServidor(servidor)
  const c = {}
  if (form.activo !== base.activo) c.activo = form.activo
  if (JSON.stringify(form.espacios) !== JSON.stringify(base.espacios)) c.espacios = cuerpoEspacios(form)
  if (JSON.stringify(form.reglas) !== JSON.stringify(base.reglas)) c.reglas = cuerpoReglas(servidor, form)
  return c
}

/** Revisa en el navegador lo escrito; el servidor valida otra vez. */
export function revisarArmador(form) {
  const e = {}
  for (const esp of form.espacios) {
    const n = Number(esp.max_unidades)
    if (!Number.isInteger(n) || n < 1 || n > MAX_UNIDADES) e[`max_${esp.clave}`] = `Escribe un número entre 1 y ${MAX_UNIDADES}.`
  }
  return e
}

/** En qué espacio está cada categoría (para no ofrecerla dos veces). */
export const espacioDeCategoria = (form) => {
  const mapa = new Map()
  for (const e of form.espacios) for (const c of e.categorias) mapa.set(c, e.clave)
  return mapa
}
