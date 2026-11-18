// Lógica pura de la pantalla «Pagos en línea» (Culqi): del servidor al formulario y de vuelta.

export const MAX_LLAVE = 80

export const MODOS = {
  PRUEBA: { texto: 'Pruebas', prefijos: ['pk_test_', 'sk_test_'], detalle: 'No cobra dinero real. Úsalo para probar que todo funciona.' },
  PRODUCCION: { texto: 'Producción', prefijos: ['pk_live_', 'sk_live_'], detalle: 'Cobra dinero real a tus clientes.' },
}

const norm = (t) => String(t ?? '').trim()

export const SI_NO_RECOGE = {
  REEMBOLSO: { texto: 'Devolver el adelanto, menos la comisión de la pasarela', detalle: 'Lo más justo con el cliente: solo pierde lo que cobró el procesador de pagos.' },
  PENALIDAD: { texto: 'Retener el adelanto como penalidad', detalle: 'Te quedas con todo el adelanto o con una parte (tú eliges el porcentaje).' },
}

/** Campos del pago con adelanto (valores del servidor → texto del formulario). */
const adelantoDesde = (d) => {
  const a = d.adelanto ?? {}
  return {
    adelanto_activo: Boolean(a.activo),
    adelanto_pct: String(Number(a.porcentaje ?? 30)),
    adelanto_minimo: String(Number(a.minimo ?? 200)),
    adelanto_dias: String(a.dias ?? 5),
    adelanto_si_no_recoge: a.si_no_recoge ?? 'REEMBOLSO',
    adelanto_penalidad_pct: String(Number(a.penalidad_pct ?? 100)),
    comision_pasarela_pct: String(Number(a.comision_pct ?? 4)),
    comision_pasarela_fija: String(Number(a.comision_fija ?? 0)),
  }
}

/** Transferencia o depósito con comprobante. */
const transferenciaDesde = (d) => {
  const t = d.transferencia ?? {}
  return {
    transferencia_activa: Boolean(t.activa),
    transferencia_horas: String(t.horas ?? 24),
    transferencia_instrucciones: t.instrucciones ?? '',
    cuentas_transferencia: [...(t.cuentas ?? [])].sort((a, b) => a - b),
  }
}

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
  ...adelantoDesde(d),
  ...transferenciaDesde(d),
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
  if (form.adelanto_activo !== base.adelanto_activo) c.adelanto_activo = form.adelanto_activo
  if (form.adelanto_si_no_recoge !== base.adelanto_si_no_recoge) c.adelanto_si_no_recoge = form.adelanto_si_no_recoge
  for (const campo of ['adelanto_pct', 'adelanto_minimo', 'adelanto_dias', 'adelanto_penalidad_pct', 'comision_pasarela_pct', 'comision_pasarela_fija']) {
    if (norm(form[campo]) !== norm(base[campo])) c[campo] = norm(form[campo])
  }
  if (form.transferencia_activa !== base.transferencia_activa) c.transferencia_activa = form.transferencia_activa
  if (norm(form.transferencia_horas) !== norm(base.transferencia_horas)) c.transferencia_horas = Number(form.transferencia_horas)
  if (norm(form.transferencia_instrucciones) !== norm(base.transferencia_instrucciones)) c.transferencia_instrucciones = norm(form.transferencia_instrucciones)
  const cuentas = [...form.cuentas_transferencia].sort((a, b) => a - b)
  if (JSON.stringify(cuentas) !== JSON.stringify(base.cuentas_transferencia)) c.cuentas_transferencia = cuentas
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
  const horas = Number(form.transferencia_horas)
  if (!(Number.isInteger(horas) && horas >= 1 && horas <= 168)) e.transferencia_horas = 'Entre 1 y 168 horas.'
  if (form.transferencia_activa && form.cuentas_transferencia.length === 0) e.cuentas_transferencia = 'Elige al menos una cuenta.'
  const pct = Number(form.adelanto_pct)
  if (!(pct >= 1 && pct <= 90)) e.adelanto_pct = 'El adelanto va del 1 % al 90 %.'
  if (!(Number(form.adelanto_minimo) >= 0)) e.adelanto_minimo = 'No puede ser negativo.'
  const dias = Number(form.adelanto_dias)
  if (!(Number.isInteger(dias) && dias >= 1 && dias <= 60)) e.adelanto_dias = 'Entre 1 y 60 días.'
  if (!(Number(form.adelanto_penalidad_pct) >= 0 && Number(form.adelanto_penalidad_pct) <= 100)) e.adelanto_penalidad_pct = 'Entre 0 y 100 %.'
  if (!(Number(form.comision_pasarela_pct) >= 0 && Number(form.comision_pasarela_pct) <= 30)) e.comision_pasarela_pct = 'Entre 0 y 30 %.'
  if (!(Number(form.comision_pasarela_fija) >= 0 && Number(form.comision_pasarela_fija) <= 50)) e.comision_pasarela_fija = 'Entre 0 y 50 soles.'
  return e
}
