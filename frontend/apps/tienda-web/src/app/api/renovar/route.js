import { timingSafeEqual } from 'node:crypto'
import { revalidatePath, revalidateTag } from 'next/cache'

/**
 * Renovar la tienda al instante cuando el panel cambia algo (producto, precio, logo, textos…).
 *
 * Solo lo usa el servidor del sistema, con un secreto compartido (RENOVAR_TOKEN). No devuelve datos
 * y solo borra lo guardado: la siguiente visita vuelve a pedir lo nuevo. Sin RENOVAR_TOKEN la ruta
 * no existe (404) y la tienda se renueva sola por tiempo.
 */
export const dynamic = 'force-dynamic'

function igual(a, b) {
  const x = Buffer.from(a)
  const y = Buffer.from(b)
  return x.length === y.length && timingSafeEqual(x, y)
}

export async function POST(request) {
  const esperado = process.env.RENOVAR_TOKEN
  if (!esperado) return new Response(null, { status: 404 })
  const recibido = (request.headers.get('authorization') || '').replace(/^Bearer\s+/i, '')
  if (!recibido || !igual(recibido, esperado)) return new Response(null, { status: 401 })
  revalidateTag('tienda', { expire: 0 })
  revalidatePath('/', 'layout')
  return Response.json({ ok: true })
}
