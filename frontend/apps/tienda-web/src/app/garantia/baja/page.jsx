import { Suspense } from 'react'
import BajaAvisosGarantia from '@/components/garantia/BajaAvisosGarantia'

export const metadata = {
  title: 'Darme de baja de los avisos de garantía',
  robots: { index: false, follow: false },
  referrer: 'no-referrer',
}

export default function Pagina() {
  return (
    <main id="contenido">
      <Suspense fallback={null}>
        <BajaAvisosGarantia />
      </Suspense>
    </main>
  )
}
