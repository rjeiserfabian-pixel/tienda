// Exportación a CSV abrible en Excel (UTF-8 con BOM, separador coma).

/**
 * Una celda que empieza con = + - @ se interpretaría como FÓRMULA en Excel (inyección de CSV):
 * se le antepone un apóstrofo para que se lea como texto.
 */
function celda(valor) {
  let texto = valor === null || valor === undefined ? '' : String(valor)
  if (/^[=+\-@\t\r]/.test(texto)) texto = `'${texto}`
  return `"${texto.replaceAll('"', '""')}"`
}

export function aCsv(encabezados, filas) {
  const lineas = [encabezados, ...filas].map((fila) => fila.map(celda).join(','))
  return `﻿${lineas.join('\r\n')}`
}

export function descargarTexto(contenido, nombreArchivo, tipo = 'text/csv;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([contenido], { type: tipo }))
  const enlace = Object.assign(document.createElement('a'), { href: url, download: nombreArchivo })
  document.body.append(enlace)
  enlace.click()
  enlace.remove()
  URL.revokeObjectURL(url)
}
