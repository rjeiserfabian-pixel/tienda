import { Suspense } from 'react'
import FormIngresar from '@/components/cuenta/FormIngresar'

export const metadata = { title: 'Ingresar', robots: { index: false, follow: false } }

export default function Pagina() {
  return (
    <main id="contenido">
      <Suspense fallback={<div className="tarjeta-centrada esqueleto-cuenta" aria-busy="true" />}>
        <FormIngresar />
      </Suspense>
    </main>
  )
}
