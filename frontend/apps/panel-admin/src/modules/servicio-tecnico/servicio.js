// Lógica pura del servicio técnico (sin React): estados, validación del ingreso y cuerpo para el servidor.

/** Los estados de una orden y el color con el que se muestran. */
export const ESTADOS_ORDEN = {
  RECIBIDO: { texto: 'Equipo recibido', tono: 'azul' },
  PENDIENTE_DIAGNOSTICO: { texto: 'Pendiente de diagnóstico', tono: 'gris' },
  EN_DIAGNOSTICO: { texto: 'En diagnóstico', tono: 'cian' },
  DIAGNOSTICADO: { texto: 'Diagnóstico realizado', tono: 'cian' },
  PENDIENTE_APROBACION: { texto: 'Pendiente de aprobación', tono: 'ambar' },
  APROBADO: { texto: 'Aprobado / Programado', tono: 'morado' },
  EN_MANTENIMIENTO: { texto: 'En mantenimiento', tono: 'azul' },
  EN_REPARACION: { texto: 'En reparación', tono: 'naranja' },
  PENDIENTE_REPUESTO: { texto: 'Pendiente de repuesto', tono: 'ambar' },
  EN_PRUEBAS: { texto: 'En pruebas', tono: 'morado' },
  TERMINADO: { texto: 'Servicio terminado', tono: 'verde' },
  LISTO_ENTREGA: { texto: 'Listo para entrega', tono: 'verde' },
  ENTREGADO: { texto: 'Entregado / Cerrado', tono: 'gris' },
  NO_APROBADO: { texto: 'No aprobado / Cancelado', tono: 'rojo' },
  SIN_SOLUCION: { texto: 'Sin solución', tono: 'rojo' },
  ABANDONADO: { texto: 'Abandonado', tono: 'rosa' },
}

export const PRIORIDADES = [
  ['NORMAL', 'Normal'],
  ['URGENTE', 'Urgente'],
]

export const RESULTADOS_REVISION = [
  ['OK', 'Bien'],
  ['FALLA', 'Con falla'],
  ['NO_PROBADO', 'No se pudo probar'],
  ['NO_APLICA', 'No aplica'],
]

export const codigoOrden = (numero) => `OS-${String(numero).padStart(6, '0')}`

/** Lo que se lee en la hoja de ingreso. Lo revisa quien administra el taller antes de usarlo. */
export const CONDICIONES_INGRESO = [
  'El equipo se recibe sin revisión interna: el estado indicado es el que se observa al ingresar.',
  'El taller no se responsabiliza por la información guardada en el equipo. Se recomienda respaldarla antes de entregarlo.',
  'El presupuesto debe ser aprobado por el cliente antes de iniciar cualquier reparación.',
  'Para retirar el equipo se debe presentar esta hoja o el documento de identidad de quien lo dejó.',
  'Pasado el plazo informado desde el aviso de que el equipo está listo, el taller podrá considerarlo abandonado.',
]

export const equipoVacio = () => ({ tipo: '', marca: '', modelo: '', numero_serie: '', color: '', descripcion: '' })

export const borradorInicial = () => ({
  cliente: null,
  equipoExistente: null, // un equipo ya registrado del cliente; si es null, se registra uno nuevo
  equipo: equipoVacio(),
  falla: '',
  estadoFisico: '',
  clave: '',
  accesorios: [], // { clave, accesorio (id o null), nombre, cantidad, detalle }
  revisiones: {}, // id de la revisión → { resultado, observacion }
  tecnico: '',
  sucursal: '',
  tipoServicio: '',
  prioridad: 'NORMAL',
  fechaPromesa: '',
  aceptaWhatsapp: false,
})

const texto = (valor) => String(valor ?? '').trim()

/**
 * Lo que se puede revisar en el navegador antes de enviar (el servidor revisa todo otra vez).
 * Devuelve `{ errores, faltan, valido }`: los errores por campo y la lista de lo que falta.
 */
export function validarIngreso(b, { hoy }) {
  const errores = {}
  const faltan = []
  const pedir = (campo, mensaje, falta) => {
    errores[campo] = mensaje
    faltan.push(falta ?? mensaje)
  }

  if (!b.cliente) pedir('cliente', 'Elija al cliente.', 'El cliente')
  if (!b.equipoExistente) {
    if (!b.equipo.tipo) pedir('tipo', 'Elija el tipo de equipo.', 'El tipo de equipo')
    if (!texto(b.equipo.marca) && !texto(b.equipo.modelo)) pedir('marca', 'Indique la marca o el modelo.', 'La marca o el modelo')
  }
  if (texto(b.falla).length < 5) pedir('falla', 'Describa la falla que reporta el cliente.', 'La falla que reporta el cliente')
  if (b.fechaPromesa && b.fechaPromesa < hoy) pedir('fechaPromesa', 'La fecha prometida no puede ser anterior a hoy.', 'Una fecha prometida válida')
  for (const a of b.accesorios) {
    if (!a.accesorio && !texto(a.nombre)) pedir('accesorios', 'Escriba el nombre del accesorio.', 'El nombre del accesorio')
    const cantidad = Number(a.cantidad)
    if (!Number.isInteger(cantidad) || cantidad < 1 || cantidad > 99) pedir('accesorios', 'La cantidad de cada accesorio va de 1 a 99.', 'La cantidad de los accesorios')
  }
  return { errores, faltan: [...new Set(faltan)], valido: faltan.length === 0 }
}

/** El cuerpo que recibe el servidor: solo lo que se llenó (las revisiones sin marcar no se envían). */
export function armarCuerpo(b, empresa) {
  const cuerpo = {
    empresa,
    cliente: b.cliente.id,
    equipo: b.equipoExistente
      ? { id: b.equipoExistente.id }
      : {
          tipo: Number(b.equipo.tipo),
          marca: texto(b.equipo.marca),
          modelo: texto(b.equipo.modelo),
          numero_serie: texto(b.equipo.numero_serie),
          color: texto(b.equipo.color),
          descripcion: texto(b.equipo.descripcion),
        },
    falla_reportada: texto(b.falla),
    estado_fisico: texto(b.estadoFisico),
    clave_equipo: texto(b.clave),
    accesorios: b.accesorios.map((a) => ({
      ...(a.accesorio ? { accesorio: a.accesorio } : { nombre: texto(a.nombre) }),
      cantidad: Number(a.cantidad),
      detalle: texto(a.detalle),
    })),
    revisiones: Object.entries(b.revisiones)
      .filter(([, r]) => r.resultado)
      .map(([item, r]) => ({ item: Number(item), resultado: r.resultado, observacion: texto(r.observacion) })),
    prioridad: b.prioridad,
    acepta_whatsapp: b.aceptaWhatsapp,
  }
  if (b.tecnico) cuerpo.tecnico = Number(b.tecnico)
  if (b.sucursal) cuerpo.sucursal = Number(b.sucursal)
  if (b.tipoServicio) cuerpo.tipo_servicio = Number(b.tipoServicio)
  if (b.fechaPromesa) cuerpo.fecha_promesa = b.fechaPromesa
  return cuerpo
}

/** Qué campo del formulario corresponde a cada error que devuelve el servidor. */
export const CAMPO_DEL_SERVIDOR = {
  cliente: 'cliente',
  equipo: 'equipo',
  falla_reportada: 'falla',
  estado_fisico: 'estadoFisico',
  clave_equipo: 'clave',
  accesorios: 'accesorios',
  revisiones: 'revisiones',
  tecnico: 'tecnico',
  sucursal: 'sucursal',
  tipo_servicio: 'tipoServicio',
  prioridad: 'prioridad',
  fecha_promesa: 'fechaPromesa',
}

/** Hace cuántos días entró (para marcar los equipos que llevan mucho en el taller). */
export const diasDesde = (iso, ahora = new Date()) => {
  const entrada = new Date(iso)
  if (Number.isNaN(entrada.getTime())) return 0
  return Math.max(0, Math.floor((ahora - entrada) / 86_400_000))
}

/** Fecha y hora cortas para las hojas impresas y el historial. */
export const fechaHora = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const dos = (n) => String(n).padStart(2, '0')
  return `${dos(d.getDate())}/${dos(d.getMonth() + 1)}/${d.getFullYear()} ${dos(d.getHours())}:${dos(d.getMinutes())}`
}

/** La dirección de la orden en el panel: quien escanea la etiqueta del equipo llega directo a su ficha. */
export const direccionDeOrden = (id) => `${window.location.origin}/servicio-tecnico/ordenes/${id}`

export const MEDIOS_AVISO = [
  ['WHATSAPP', 'WhatsApp'],
  ['LLAMADA', 'Llamada'],
  ['CORREO', 'Correo'],
  ['PRESENCIAL', 'En persona'],
  ['OTRO', 'Otro medio'],
]

/** Cómo está cada repuesto del presupuesto respecto de su stock. */
export const ESTADOS_REPUESTO = {
  PENDIENTE: { texto: 'Sin reservar', tono: 'ambar' },
  RESERVADO: { texto: 'Reservado', tono: 'azul' },
  CONSUMIDO: { texto: 'Usado', tono: 'verde' },
  LIBERADO: { texto: 'Devuelto al almacén', tono: 'gris' },
}

let contadorLineas = 0
const nuevaClave = () => `lp-${++contadorLineas}`

/** Una línea del presupuesto a partir de un producto del catálogo de venta. */
export function lineaDeFicha(ficha, empresaOrden, lista) {
  const lleva = ficha.controla_stock
  const conStock = (ficha.stock ?? []).filter((s) => Number(s.cantidad) > 0)
  const empresa = lleva && !conStock.some((s) => s.empresa === empresaOrden) && conStock.length ? conStock[0].empresa : empresaOrden
  const precio = (ficha.precios ?? []).find((p) => p.lista === lista)?.precio ?? null
  return { clave: nuevaClave(), producto: ficha.id, nombre: ficha.nombre, codigo: ficha.codigo, tipo: ficha.tipo, empresa, cantidad: '1', precio: '', precioLista: precio, stock: ficha.stock ?? null }
}

/** Las líneas del presupuesto vigente, listas para editarlas (el precio solo se rellena si se había cambiado). */
export const lineasDePresupuesto = (presupuesto) =>
  presupuesto.lineas.map((l) => ({
    clave: nuevaClave(),
    producto: l.producto,
    nombre: l.descripcion,
    codigo: l.codigo,
    tipo: l.tipo,
    empresa: l.empresa,
    cantidad: String(Number(l.cantidad)),
    precio: l.precio_unitario && l.precio_lista && Number(l.precio_unitario) !== Number(l.precio_lista) ? String(Number(l.precio_unitario)) : '',
    precioLista: l.precio_lista ? String(l.precio_lista) : null,
    stock: null,
  }))

/** Lo que se puede revisar antes de enviar el presupuesto. */
export function validarPresupuesto(lineas) {
  if (lineas.length === 0) return 'Agrega al menos un servicio o repuesto.'
  for (const l of lineas) {
    const cantidad = Number(l.cantidad)
    if (!Number.isFinite(cantidad) || cantidad <= 0) return `La cantidad de «${l.nombre}» debe ser mayor que cero.`
    if (l.precio !== '' && !(Number(l.precio) > 0)) return `El precio de «${l.nombre}» debe ser mayor que cero (o déjalo vacío para usar el de lista).`
  }
  return ''
}

export const cuerpoPresupuesto = (lineas, validezDias, condiciones) => ({
  lineas: lineas.map((l) => ({
    producto: l.producto,
    cantidad: String(l.cantidad).replace(',', '.'),
    empresa: l.empresa,
    ...(l.precio !== '' ? { precio_unitario: String(l.precio).replace(',', '.') } : {}),
  })),
  validez_dias: Number(validezDias),
  ...(condiciones.trim() ? { condiciones: condiciones.trim() } : {}),
})

/** Lo que dice el acta de entrega sobre la garantía. Lo revisa quien administra el taller antes de usarlo. */
export const CONDICIONES_GARANTIA = [
  'La garantía cubre únicamente el trabajo realizado y los repuestos cambiados, por los días indicados.',
  'No cubre golpes, humedad, sobrecargas, manipulación por terceros ni fallas distintas a la reparada.',
  'Para hacerla valer se debe presentar esta acta y el equipo con los sellos o etiquetas del taller.',
]
