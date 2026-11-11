import { Suspense } from 'react'
import CompararVista from '@/components/CompararVista'

export const metadata = {
  title: 'Comparar productos',
  description: 'Compara hasta 4 productos lado a lado: precios, disponibilidad y especificaciones.',
  robots: { index: false, follow: true },
  alternates: { canonical: '/comparar' },
}

export default function PaginaComparar() {
  return (
    <main id="contenido" className="contenedor cmp-pagina">
      <h1>Comparar productos</h1>
      <p className="cmp-sub">Mira lado a lado lo que cambia entre ellos y elige con seguridad.</p>
      <Suspense fallback={<div className="esqueleto cmp-esq-cab" aria-hidden="true" />}>
        <CompararVista />
      </Suspense>
    </main>
  )
}
