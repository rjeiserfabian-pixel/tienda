import Link from 'next/link'
import { urlAbsoluta } from '@/lib/format'
import JsonLd from './JsonLd'

/**
 * Ruta de navegación (Inicio › Familia › Categoría). El último elemento no lleva enlace.
 * También entrega a Google la ruta como datos estructurados.
 */
export default function Migas({ items }) {
  const datos = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: items.map((it, i) => ({
      '@type': 'ListItem',
      position: i + 1,
      name: it.nombre,
      ...(it.href ? { item: urlAbsoluta(it.href) } : {}),
    })),
  }
  return (
    <nav aria-label="Ruta de navegación" className="migas">
      <ol>
        {items.map((it, i) => (
          <li key={`${it.nombre}-${i}`}>
            {it.href && i < items.length - 1 ? (
              <Link href={it.href}>{it.nombre}</Link>
            ) : (
              <span aria-current={i === items.length - 1 ? 'page' : undefined}>{it.nombre}</span>
            )}
          </li>
        ))}
      </ol>
      <JsonLd datos={datos} />
    </nav>
  )
}
