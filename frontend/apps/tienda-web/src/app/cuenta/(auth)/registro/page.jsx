import { Suspense } from 'react'
import FormRegistro from '@/components/cuenta/FormRegistro'

export const metadata = { title: 'Crear cuenta', robots: { index: false, follow: false } }

export default function Pagina() {
  return (
    <main id="contenido">
      <Suspense fallback={<div className="tarjeta-centrada esqueleto-cuenta" aria-busy="true" />}>
        <FormRegistro />
      </Suspense>
    </main>
  )
}
