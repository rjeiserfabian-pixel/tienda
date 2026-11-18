'use client'

import { useEffect } from 'react'
import { medir } from '@/lib/medicion'

/** Avisa a la medición (si el visitante la aceptó) que se vio un producto, se empezó a pagar o se compró. */
export default function MedirVista({ evento, datos, clave }) {
  useEffect(() => {
    if (clave) {
      try {
        if (window.sessionStorage.getItem(`medido:${clave}`)) return // una sola vez por visita
        window.sessionStorage.setItem(`medido:${clave}`, '1')
      } catch {
        // sin almacenamiento: puede repetirse, no pasa nada grave
      }
    }
    medir(evento, datos)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [evento, clave])
  return null
}
