// Lógica pura de la pantalla «Envíos y recojo»: del servidor al formulario y de vuelta.

export const MAX_TRAMOS = 20
export const MAX_LUGARES = 400
export const MODALIDADES = {
  TIENDA: { texto: 'Reparto propio', ayuda: 'El envío se cobra en la compra, según el peso. Ej.: Lima con tu moto o tu courier.' },
  DESTINO: { texto: 'Agencia (pago en destino)', ayuda: 'El cliente paga el flete al recibir; tú solo cobras el producto. Ej.: Olva o Shalom a provincias.' },
}

const norm = (t) => String(t ?? '').trim().replace(/\s+/g, ' ')
const decimal = (t) => String(t ?? '').trim().replace(',', '.')
const esMonto = (t) => /^\d{1,8}(\.\d{1,2})?$/.test(decimal(t))

/** Zona nueva con valores de partida razonables. */
export const zonaVacia = () => ({
  id: null,
  nombre: '',
  modalidad: 'TIENDA',
  plazo: '',
  detalle: '',
  activa: true,
  envio_gratis_desde: '',
  kg_adicional: '',
  tarifas: [{ hasta_kg: '', costo: '' }],
  coberturas: [],
})

/** Lo que devuelve el servidor → los valores del formulario (todo como texto). */
export const zonaDesdeServidor = (z) => ({
  id: z.id,
  nombre: z.nombre ?? '',
  modalidad: z.modalidad,
  plazo: z.plazo ?? '',
  detalle: z.detalle ?? '',
  activa: Boolean(z.activa),
  envio_gratis_desde: z.envio_gratis_desde ?? '',
  kg_adicional: z.kg_adicional ?? '',
  tarifas: z.tarifas.length ? z.tarifas.map((t) => ({ hasta_kg: String(t.hasta_kg), costo: String(t.costo) })) : [{ hasta_kg: '', costo: '' }],
  coberturas: z.coberturas.map((c) => ({ prefijo: c.prefijo, nombre: c.nombre })),
})

/** Revisa en el navegador lo escrito; el servidor valida otra vez. */
export function revisarZona(f) {
  const e = {}
  if (!norm(f.nombre)) e.nombre = 'Escribe el nombre de la zona.'
  if (f.modalidad === 'TIENDA') {
    const tramos = f.tarifas.filter((t) => norm(t.hasta_kg) || norm(t.costo))
    if (tramos.length === 0) e.tarifas = 'Pon al menos un tramo de peso con su costo.'
    else if (tramos.some((t) => !esMonto(t.hasta_kg) || Number(decimal(t.hasta_kg)) <= 0 || !esMonto(t.costo))) {
      e.tarifas = 'Cada tramo necesita un peso mayor a 0 y un costo (0 o más), con hasta 2 decimales.'
    } else if (new Set(tramos.map((t) => Number(decimal(t.hasta_kg)))).size !== tramos.length) {
      e.tarifas = 'Hay dos tramos con el mismo peso.'
    }
    if (norm(f.envio_gratis_desde) && !esMonto(f.envio_gratis_desde)) e.envio_gratis_desde = 'Escribe un monto válido, ej. 300.'
    if (norm(f.kg_adicional) && !esMonto(f.kg_adicional)) e.kg_adicional = 'Escribe un monto válido, ej. 3.'
  }
  if (f.coberturas.length === 0) e.coberturas = 'Agrega al menos un lugar que cubra esta zona.'
  return e
}

/** Cuerpo para el servidor. En agencia no se mandan tarifas ni montos. */
export function cuerpoDeZona(f) {
  const tienda = f.modalidad === 'TIENDA'
  return {
    nombre: norm(f.nombre),
    modalidad: f.modalidad,
    plazo: norm(f.plazo),
    detalle: norm(f.detalle),
    activa: f.activa,
    envio_gratis_desde: tienda && norm(f.envio_gratis_desde) ? decimal(f.envio_gratis_desde) : null,
    kg_adicional: tienda && norm(f.kg_adicional) ? decimal(f.kg_adicional) : null,
    tarifas: tienda
      ? f.tarifas
          .filter((t) => norm(t.hasta_kg) || norm(t.costo))
          .map((t) => ({ hasta_kg: decimal(t.hasta_kg), costo: decimal(t.costo) }))
          .sort((a, b) => Number(a.hasta_kg) - Number(b.hasta_kg))
      : [],
    coberturas: f.coberturas.map((c) => c.prefijo),
  }
}

export const soles = (valor) => `S/ ${Number(valor).toFixed(2)}`

/** «Hasta 2 kg: S/ 10.00 · Hasta 5 kg: S/ 15.00 …» en pocas palabras. */
export function resumenTarifas(zona) {
  if (zona.modalidad === 'DESTINO') return 'Sin costo en la compra: el cliente paga el flete al recibir.'
  if (!zona.tarifas.length) return 'Sin tarifas.'
  const tramos = zona.tarifas.map((t) => `hasta ${Number(t.hasta_kg)} kg: ${soles(t.costo)}`)
  const extra = zona.kg_adicional ? ` · luego ${soles(zona.kg_adicional)} por kg adicional` : ''
  return tramos.join(' · ') + extra
}

export const nombreDepartamento = (d) => `${d.nombre}`.toUpperCase()

/** Punto de recojo nuevo. */
export const puntoVacio = () => ({
  id: null,
  nombre: '',
  direccion: '',
  horario: '',
  indicaciones: '',
  listo_en: '',
  telefono: '',
  activo: true,
  almacenes: [],
})

export const puntoDesdeServidor = (p) => ({
  id: p.id,
  nombre: p.nombre ?? '',
  direccion: p.direccion ?? '',
  horario: p.horario ?? '',
  indicaciones: p.indicaciones ?? '',
  listo_en: p.listo_en ?? '',
  telefono: p.telefono ?? '',
  activo: Boolean(p.activo),
  almacenes: [...(p.almacenes ?? [])].sort((a, b) => a - b),
})

export function revisarPunto(f) {
  const e = {}
  if (!norm(f.nombre)) e.nombre = 'Escribe el nombre del punto.'
  if (!norm(f.direccion)) e.direccion = 'Escribe la dirección.'
  if (f.telefono.trim() && !/^[\d +()-]{6,20}$/.test(f.telefono.trim())) e.telefono = 'Escribe un teléfono válido.'
  return e
}

export const cuerpoDePunto = (f) => ({
  nombre: norm(f.nombre),
  direccion: norm(f.direccion),
  horario: norm(f.horario),
  indicaciones: norm(f.indicaciones),
  listo_en: norm(f.listo_en),
  telefono: norm(f.telefono),
  activo: f.activo,
  almacenes: [...f.almacenes].sort((a, b) => a - b),
})

/** Ajustes generales de entrega (van a la configuración de la tienda). */
export const ajustesDesdeServidor = (d) => ({
  permite_envio: Boolean(d.permite_envio),
  permite_recojo: Boolean(d.permite_recojo),
  peso_por_defecto_kg: String(d.peso_por_defecto_kg ?? '1'),
})

export function cambiosDeAjustes(servidor, form) {
  const base = ajustesDesdeServidor(servidor)
  const c = {}
  if (form.permite_envio !== base.permite_envio) c.permite_envio = form.permite_envio
  if (form.permite_recojo !== base.permite_recojo) c.permite_recojo = form.permite_recojo
  if (decimal(form.peso_por_defecto_kg) !== decimal(base.peso_por_defecto_kg) && decimal(form.peso_por_defecto_kg) !== '') {
    c.peso_por_defecto_kg = decimal(form.peso_por_defecto_kg)
  }
  return c
}

export function revisarAjustes(form) {
  const e = {}
  const peso = decimal(form.peso_por_defecto_kg)
  if (!/^\d{1,4}(\.\d{1,2})?$/.test(peso) || Number(peso) <= 0) e.peso_por_defecto_kg = 'Escribe un peso mayor a 0, ej. 1 o 1.5.'
  return e
}
