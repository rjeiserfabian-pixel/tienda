// Lógica pura de «Ofertas y banners» de la tienda: estados, fechas y validaciones.

export const ESTADOS_OFERTA = {
  VIGENTE: { texto: 'Vigente', tono: 'verde' },
  PROGRAMADA: { texto: 'Programada', tono: 'azul' },
  VENCIDA: { texto: 'Vencida', tono: 'gris' },
  PAUSADA: { texto: 'Pausada', tono: 'ambar' },
}

export const ESTADOS_BANNER = {
  VIGENTE: { texto: 'Se muestra', tono: 'verde' },
  PROGRAMADO: { texto: 'Programado', tono: 'azul' },
  VENCIDO: { texto: 'Vencido', tono: 'gris' },
  PAUSADO: { texto: 'Pausado', tono: 'ambar' },
  SIN_IMAGEN: { texto: 'Sin imagen', tono: 'rojo' },
}

export const FILTROS_ESTADO = [
  { valor: '', texto: 'Todas' },
  { valor: 'VIGENTE', texto: 'Vigentes' },
  { valor: 'PROGRAMADA', texto: 'Programadas' },
  { valor: 'VENCIDA', texto: 'Vencidas' },
  { valor: 'PAUSADA', texto: 'Pausadas' },
]

export const MAX_BYTES_BANNER = 3 * 1024 * 1024
export const TIPOS_IMAGEN = ['image/jpeg', 'image/png', 'image/webp']

const dos = (n) => String(n).padStart(2, '0')

/** ISO del servidor → valor de un <input type="datetime-local"> en la hora del navegador. */
export const aCampoFecha = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())}T${dos(d.getHours())}:${dos(d.getMinutes())}`
}

/** Valor de <input type="datetime-local"> → ISO con zona (lo que el servidor espera). */
export const desdeCampoFecha = (valor) => {
  if (!valor) return null
  const d = new Date(valor)
  return Number.isNaN(d.getTime()) ? null : d.toISOString()
}

/** Ahora + `horas`, para proponer fechas al crear una oferta. */
export const enHoras = (horas) => aCampoFecha(new Date(Date.now() + horas * 3_600_000).toISOString())

export const soles = (valor) => {
  const n = Number(valor)
  return Number.isFinite(n) ? `S/ ${n.toLocaleString('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'
}

export const fechaHora = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return `${dos(d.getDate())}/${dos(d.getMonth() + 1)}/${d.getFullYear()} ${dos(d.getHours())}:${dos(d.getMinutes())}`
}

// ---------------------------------------------------------------- ofertas
export const ofertaVacia = () => ({
  id: null,
  producto: null, // { id, codigo, nombre, precio_normal }
  precio_oferta: '',
  desde: enHoras(0),
  hasta: enHoras(24 * 7),
  etiqueta: '',
  activa: true,
})

export const ofertaDesdeServidor = (o) => ({
  id: o.id,
  producto: { id: o.producto.id, codigo: o.producto.codigo, nombre: o.producto.nombre, precio_normal: o.precio_normal },
  precio_oferta: String(o.precio_oferta ?? ''),
  desde: aCampoFecha(o.desde),
  hasta: aCampoFecha(o.hasta),
  etiqueta: o.etiqueta ?? '',
  activa: Boolean(o.activa),
})

/** Errores que se pueden ver sin llamar al servidor. */
export function revisarOferta(f) {
  const e = {}
  if (!f.producto) e.producto = 'Elige el producto.'
  const precio = Number(f.precio_oferta)
  if (!f.precio_oferta || !Number.isFinite(precio) || precio <= 0) e.precio_oferta = 'Escribe el precio de oferta.'
  else if (f.producto?.precio_normal && precio >= Number(f.producto.precio_normal)) {
    e.precio_oferta = `Debe ser menor que el precio normal (${soles(f.producto.precio_normal)}).`
  }
  if (!f.desde) e.desde = 'Indica cuándo empieza.'
  if (!f.hasta) e.hasta = 'Indica cuándo termina.'
  if (f.desde && f.hasta && new Date(f.hasta) <= new Date(f.desde)) e.hasta = 'Debe terminar después de empezar.'
  return e
}

export const cuerpoDeOferta = (f) => ({
  producto: f.producto.id,
  precio_oferta: String(f.precio_oferta).trim(),
  desde: desdeCampoFecha(f.desde),
  hasta: desdeCampoFecha(f.hasta),
  etiqueta: f.etiqueta.trim(),
  activa: f.activa,
})

/** Ahorro en % entre el precio normal y el de oferta (o `null` si falta algo). */
export function ahorroPct(normal, oferta) {
  const n = Number(normal)
  const o = Number(oferta)
  if (!Number.isFinite(n) || !Number.isFinite(o) || n <= 0 || o <= 0 || o >= n) return null
  return Math.round((1 - o / n) * 100)
}

// ---------------------------------------------------------------- banners
export const bannerVacio = () => ({
  id: null,
  titulo: '',
  subtitulo: '',
  boton_texto: '',
  enlace: '',
  alt: '',
  orden: '0',
  desde: '',
  hasta: '',
  activo: true,
  tiene_escritorio: false,
  tiene_movil: false,
  version: '',
})

export const bannerDesdeServidor = (b) => ({
  id: b.id,
  titulo: b.titulo ?? '',
  subtitulo: b.subtitulo ?? '',
  boton_texto: b.boton_texto ?? '',
  enlace: b.enlace ?? '',
  alt: b.alt ?? '',
  orden: String(b.orden ?? 0),
  desde: aCampoFecha(b.desde),
  hasta: aCampoFecha(b.hasta),
  activo: Boolean(b.activo),
  tiene_escritorio: Boolean(b.tiene_escritorio),
  tiene_movil: Boolean(b.tiene_movil),
  version: b.version ?? '',
})

/** Mismas reglas que el servidor: ruta de la tienda (/ofertas) o URL https. */
export const enlaceValido = (enlace) => !enlace || /^\/(?!\/)[A-Za-z0-9\-._~/%?=&#]*$/.test(enlace) || /^https:\/\/\S+$/.test(enlace)

export function revisarBanner(f, { escritorio, requiereEscritorio }) {
  const e = {}
  if (!f.titulo.trim()) e.titulo = 'Escribe el título.'
  if (!f.alt.trim()) e.alt = 'Describe la imagen para quienes usan lector de pantalla.'
  if (!enlaceValido(f.enlace.trim())) e.enlace = 'Usa una dirección de la tienda (ej.: /ofertas) o una URL que empiece con https://.'
  if (f.boton_texto.trim() && !f.enlace.trim()) e.enlace = 'Para mostrar un botón escribe también el enlace.'
  if (requiereEscritorio && !escritorio && !f.tiene_escritorio) e.imagen_escritorio = 'Sube la imagen para computadora.'
  if (f.desde && f.hasta && new Date(f.hasta) <= new Date(f.desde)) e.hasta = 'Debe terminar después de empezar.'
  const orden = Number(f.orden)
  if (!Number.isInteger(orden) || orden < 0 || orden > 1000) e.orden = 'Escribe un número entre 0 y 1000.'
  return e
}

/** Los banners viajan como formulario (llevan archivos). Solo se manda lo que tiene valor. */
export function formularioDeBanner(f, { escritorio, movil, quitarMovil }) {
  const cuerpo = new FormData()
  cuerpo.append('titulo', f.titulo.trim())
  cuerpo.append('subtitulo', f.subtitulo.trim())
  cuerpo.append('boton_texto', f.boton_texto.trim())
  cuerpo.append('enlace', f.enlace.trim())
  cuerpo.append('alt', f.alt.trim())
  cuerpo.append('orden', String(Number(f.orden) || 0))
  cuerpo.append('activo', f.activo ? 'true' : 'false')
  const desde = desdeCampoFecha(f.desde)
  const hasta = desdeCampoFecha(f.hasta)
  cuerpo.append('desde', desde ?? '')
  cuerpo.append('hasta', hasta ?? '')
  if (escritorio) cuerpo.append('imagen_escritorio', escritorio)
  if (movil) cuerpo.append('imagen_movil', movil)
  else if (quitarMovil) cuerpo.append('quitar_imagen_movil', 'true')
  return cuerpo
}

/** Revisa un archivo de imagen antes de subirlo; devuelve un mensaje o `''`. */
export function errorDeArchivo(archivo) {
  if (!archivo) return ''
  if (!TIPOS_IMAGEN.includes(archivo.type)) return 'Usa una imagen JPG, PNG o WEBP.'
  if (archivo.size > MAX_BYTES_BANNER) return 'La imagen pesa más de 3 MB.'
  return ''
}
