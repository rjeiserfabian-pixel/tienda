/**
 * Datos estructurados para Google (schema.org). El contenido sale de la API (nombres de productos),
 * así que se escapa el `<` para que nada pueda cerrar la etiqueta <script> y ejecutar código.
 * Los separadores U+2028 y U+2029 se arman con códigos (sin escribirlos literales en el archivo).
 */
const SEPARADORES = new RegExp(`${String.fromCharCode(8232)}|${String.fromCharCode(8233)}`, 'g')

export default function JsonLd({ datos }) {
  // '\\u003c' (con doble barra) es el TEXTO <; con una sola barra JavaScript lo convertiría
  // en «<» y el escape no haría nada.
  const json = JSON.stringify(datos).replace(/</g, '\\u003c').replace(SEPARADORES, '')
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: json }} />
}
