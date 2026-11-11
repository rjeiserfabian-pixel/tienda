'use client'

import { useRouter } from 'next/navigation'
import { useId, useTransition } from 'react'
import { enlaceConFiltros, ORDENES } from '@/lib/filtros'

/** «Ordenar por»: cambia el orden navegando a la misma dirección con `?orden=…` (vuelve a la página 1). */
export default function Ordenar({ rutaBase, filtros }) {
  const id = useId()
  const router = useRouter()
  const [pendiente, empezar] = useTransition()
  return (
    <div className="lis-ordenar">
      <label htmlFor={id}>Ordenar por</label>
      <select
        id={id}
        value={filtros.orden}
        disabled={pendiente}
        onChange={(e) => {
          const orden = e.target.value
          empezar(() => router.push(enlaceConFiltros(rutaBase, filtros, { orden }), { scroll: false }))
        }}
      >
        {ORDENES.map((o) => (
          <option key={o.valor} value={o.valor}>
            {o.texto}
          </option>
        ))}
      </select>
    </div>
  )
}
