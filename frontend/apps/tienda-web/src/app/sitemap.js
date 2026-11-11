import { obtenerMapaDelSitio } from '@/lib/api'
import { urlAbsoluta } from '@/lib/format'

export const revalidate = 300

/** Las direcciones públicas de la tienda, para que Google las indexe. */
export default async function sitemap() {
  const fijas = [
    { url: urlAbsoluta('/'), changeFrequency: 'daily', priority: 1 },
    { url: urlAbsoluta('/ofertas'), changeFrequency: 'daily', priority: 0.7 },
    { url: urlAbsoluta('/arma-tu-pc'), changeFrequency: 'weekly', priority: 0.5 },
    { url: urlAbsoluta('/servicio-tecnico'), changeFrequency: 'monthly', priority: 0.5 },
  ]
  try {
    const mapa = await obtenerMapaDelSitio()
    return [
      ...fijas,
      ...mapa.categorias.map((s) => ({ url: urlAbsoluta(`/categoria/${s}`), changeFrequency: 'daily', priority: 0.8 })),
      ...mapa.marcas.map((s) => ({ url: urlAbsoluta(`/marca/${s}`), changeFrequency: 'weekly', priority: 0.6 })),
      ...mapa.productos.map((p) => ({
        url: urlAbsoluta(`/producto/${p.slug}`),
        lastModified: p.actualizado,
        changeFrequency: 'weekly',
        priority: 0.7,
      })),
    ]
  } catch {
    return fijas // la API no respondió: se sirve lo mínimo y se reintenta en la próxima visita
  }
}
