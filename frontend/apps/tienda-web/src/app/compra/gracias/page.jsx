import { Suspense } from 'react'
import GraciasVista from '@/components/GraciasVista'
import '@/app/compra.css'
import '@/app/pedidos.css'

export const metadata = {
  title: 'Gracias por tu compra',
  robots: { index: false, follow: false },
}

export default function PaginaGracias() {
  return (
    <main id="contenido" className="contenedor pagina compra-pagina">
      <Suspense fallback={<span className="esqueleto" style={{ height: 320, borderRadius: 14 }} />}>
        <GraciasVista />
      </Suspense>
    </main>
  )
}
