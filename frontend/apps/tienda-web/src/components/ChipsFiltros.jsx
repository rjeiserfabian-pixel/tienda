import Link from 'next/link'
import { enlaceConFiltros, hayFiltros } from '@/lib/filtros'
import Icono from './Icono'
import { etiquetaDeEspecificacion } from './listado-util'

/**
 * Los filtros aplicados como chips; cada uno lleva una × que es un enlace que lo quita.
 * `rutaLimpia` es la dirección sin ningún filtro (en una búsqueda conserva el texto buscado).
 */
export default function ChipsFiltros({ rutaBase, rutaLimpia, filtros, facetas, marcaFija, marcasConocidas }) {
  const chips = []
  const quitar = (cambios) => enlaceConFiltros(rutaBase, filtros, cambios)

  if (filtros.q && rutaBase !== '/buscar') chips.push({ clave: 'q', texto: `Texto: ${filtros.q}`, href: quitar({ q: '' }) })
  if (!marcaFija) {
    for (const slug of filtros.marca) {
      const nombre =
        facetas?.marcas?.find((m) => m.slug === slug)?.nombre ?? marcasConocidas?.find((m) => m.slug === slug)?.nombre ?? slug
      chips.push({ clave: `m-${slug}`, texto: nombre, href: quitar({ marca: filtros.marca.filter((m) => m !== slug) }) })
    }
  }
  if (filtros.precio_min || filtros.precio_max) {
    const texto =
      filtros.precio_min && filtros.precio_max
        ? `S/ ${filtros.precio_min} – S/ ${filtros.precio_max}`
        : filtros.precio_min
          ? `Desde S/ ${filtros.precio_min}`
          : `Hasta S/ ${filtros.precio_max}`
    chips.push({ clave: 'precio', texto, href: quitar({ precio_min: '', precio_max: '' }) })
  }
  if (filtros.disponible) chips.push({ clave: 'stock', texto: 'Solo con stock', href: quitar({ disponible: false }) })
  if (filtros.nuevo && rutaBase !== '/buscar') chips.push({ clave: 'nuevo', texto: 'Novedades', href: quitar({ nuevo: false }) })
  if (filtros.destacado && rutaBase !== '/buscar') chips.push({ clave: 'dest', texto: 'Destacados', href: quitar({ destacado: false }) })
  for (const [clave, valores] of Object.entries(filtros.esp)) {
    for (const valor of valores) {
      const { campo, texto } = etiquetaDeEspecificacion(facetas, clave, valor)
      const restantes = valores.filter((v) => v !== valor)
      const esp = { ...filtros.esp }
      if (restantes.length) esp[clave] = restantes
      else delete esp[clave]
      chips.push({ clave: `e-${clave}-${valor}`, texto: `${campo}: ${texto}`, href: quitar({ esp }) })
    }
  }
  if (chips.length === 0) return null

  return (
    <div className="lis-chips" role="group" aria-label="Filtros aplicados">
      <ul>
        {chips.map((c) => (
          <li key={c.clave}>
            <Link href={c.href} className="lis-chip" scroll={false} aria-label={`Quitar el filtro ${c.texto}`}>
              <span>{c.texto}</span>
              <Icono nombre="cerrar" tam={14} />
            </Link>
          </li>
        ))}
      </ul>
      {hayFiltros(filtros) && (
        <Link href={rutaLimpia} className="lis-limpiar" scroll={false}>
          Limpiar todo
        </Link>
      )}
    </div>
  )
}
