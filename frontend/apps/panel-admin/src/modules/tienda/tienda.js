// Lógica pura del módulo «Tienda virtual»: qué le falta a la ficha de un producto y utilidades de texto.

/** Lo que una ficha necesita para verse completa en la tienda, en el orden en que se muestra. */
export const REQUISITOS_FICHA = [
  { clave: 'foto', texto: 'foto', falta: (p) => !p.foto_principal },
  { clave: 'descripcion', texto: 'descripción', falta: (p) => !String(p.descripcion_web ?? '').trim() },
  { clave: 'puntos', texto: 'puntos destacados', falta: (p) => !(p.puntos_destacados?.length > 0) },
  { clave: 'especificaciones', texto: 'especificaciones', falta: (p) => Object.keys(p.especificaciones ?? {}).length === 0 },
  { clave: 'garantia', texto: 'garantía', falta: (p) => p.garantia_meses === null || p.garantia_meses === undefined },
  {
    clave: 'envio',
    texto: 'peso y medidas',
    falta: (p) => [p.peso_kg, p.largo_cm, p.ancho_cm, p.alto_cm].some((v) => v === null || v === undefined || v === ''),
  },
]

/** Lista de lo que falta en la ficha de un producto (vacía si está completa). */
export const faltantesDeFicha = (producto) => REQUISITOS_FICHA.filter((r) => r.falta(producto)).map((r) => r.texto)

/** Avance de la ficha de 0 a 100. */
export const avanceDeFicha = (producto) => Math.round(((REQUISITOS_FICHA.length - faltantesDeFicha(producto).length) / REQUISITOS_FICHA.length) * 100)

/** Minúsculas y sin tildes: para buscar «camara» y encontrar «Cámara». */
export const plano = (texto) =>
  String(texto ?? '')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .trim()

/** «1 dato» / «24 datos». */
export const datosTexto = (n) => `${n} ${n === 1 ? 'dato' : 'datos'}`
