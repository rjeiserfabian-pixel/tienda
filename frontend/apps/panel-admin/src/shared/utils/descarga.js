import { api, mensajeDeError } from '../../core/api/client'

/**
 * Descarga un archivo que el servidor genera al momento (Excel, PDF). Se pide con el token y se
 * entrega al navegador como adjunto: un enlace simple no podría enviar la sesión.
 * Devuelve el nombre del archivo.
 */
export async function descargarArchivo(url, params) {
  const respuesta = await api.get(url, { params, responseType: 'blob', timeout: 120_000 })
  const nombre = /filename="([^"]+)"/.exec(respuesta.headers['content-disposition'] ?? '')?.[1] ?? 'reporte'
  const objeto = URL.createObjectURL(respuesta.data)
  const enlace = document.createElement('a')
  enlace.href = objeto
  enlace.download = nombre
  document.body.append(enlace)
  enlace.click()
  enlace.remove()
  setTimeout(() => URL.revokeObjectURL(objeto), 10_000)
  return nombre
}

/** Con `responseType: 'blob'` el error del servidor también llega como blob: se lee para mostrarlo. */
export async function mensajeDeErrorDescarga(error) {
  const cuerpo = error?.response?.data
  if (cuerpo instanceof Blob) {
    try {
      const json = JSON.parse(await cuerpo.text())
      if (json?.error?.mensaje) return json.error.mensaje
    } catch {
      /* no era JSON: se usa el mensaje general */
    }
  }
  return mensajeDeError(error)
}
