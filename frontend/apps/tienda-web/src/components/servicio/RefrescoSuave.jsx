'use client'

import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

const CADA_MS = 120_000

/**
 * Mantiene al día el estado sin que el cliente recargue: cada 2 minutos vuelve a pedirlo, pero solo
 * si la pestaña se está viendo (no gasta consultas en una pestaña olvidada).
 */
export default function RefrescoSuave() {
  const router = useRouter()
  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') router.refresh()
    }, CADA_MS)
    return () => clearInterval(id)
  }, [router])
  return null
}
