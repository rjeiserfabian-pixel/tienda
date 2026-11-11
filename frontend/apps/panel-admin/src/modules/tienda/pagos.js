// Lógica pura de la pantalla «Pagos en línea» (Culqi): del servidor al formulario y de vuelta.

export const MAX_LLAVE = 80

export const MODOS = {
  PRUEBA: { texto: 'Pruebas', prefijos: ['pk_test_', 'sk_test_'], detalle: 'No cobra dinero real. Úsalo para probar que todo funciona.' },
  PRODUCCION: { texto: 'Producción', prefijos: ['pk_live_', 'sk_live_'], detalle: 'Cobra dinero real a tus clientes.' },
}

const norm = (t) => String(t ?? '').trim()

/** Lo que devuelve el servidor → los valores del formulario. La llave secreta nunca viene: empieza vacía. */
export const desdeServidor = (d) => ({
  culqi_activo: Boolean(d.culqi_activo),
  culqi_modo: d.culqi_modo ?? 'PRUEBA',
  culqi_llave_publica: d.culqi_llave_publica ?? '',
  culqi_llave_secreta: '',
  quitar_llave_secreta: false,
  acepta_tarjeta: Boolean(d.acepta_tarjeta),
  acepta_yape: Boolean(d.acepta_yape),
  empresa_cobra: d.empresa_cobra === null || d.empresa_cobra === undefined ? '' : String(d.empresa_cobra),
})

/** Solo lo que cambió, con el tipo que espera el servidor. */
export function cambiosDePagos(servidor, form) {
  const base = desdeServidor(servidor)
  const c = {}
  if (form.culqi_modo !== base.culqi_modo) c.culqi_modo = form.culqi_modo
  if (norm(form.culqi_llave_publica) !== norm(base.culqi_llave_publica)) c.culqi_llave_publica = norm(form.culqi_llave_publica)
  if (form.quitar_llave_secreta) c.quitar_llave_secreta = true
  else if (norm(form.culqi_llave_secreta)) c.culqi_llave_secreta = norm(form.culqi_llave_secreta)
  if (form.acepta_tarjeta !== base.acepta_tarjeta) c.acepta_tarjeta = form.acepta_tarjeta
  if (form.acepta_yape !== base.acepta_yape) c.acepta_yape = form.acepta_yape
  if (form.empresa_cobra !== base.empresa_cobra) c.empresa_cobra = form.empresa_cobra === '' ? null : Number(form.empresa_cobra)
  if (form.culqi_activo !== base.culqi_activo) c.culqi_activo = form.culqi_activo
  return c
}

/** Revisa en el navegador lo escrito; el servidor valida otra vez. */
export function revisarPagos(form) {
  const e = {}
  const [pk, sk] = MODOS[form.culqi_modo].prefijos
  const publica = norm(form.culqi_llave_publica)
  if (publica && !publica.startsWith(pk)) e.culqi_llave_publica = `En modo ${MODOS[form.culqi_modo].texto} la llave pública empieza con «${pk}».`
  const secreta = norm(form.culqi_llave_secreta)
  if (secreta && !secreta.startsWith(sk)) e.culqi_llave_secreta = `En modo ${MODOS[form.culqi_modo].texto} la llave secreta empieza con «${sk}».`
  return e
}
