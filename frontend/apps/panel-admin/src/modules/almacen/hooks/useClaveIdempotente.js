import { useState } from 'react'

const nueva = () =>
  globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`

/**
 * Clave de idempotencia para registrar UNA vez. Mientras el contenido no cambie se conserva: si
 * el envío se repite (doble clic, red lenta) el servidor devuelve el mismo resultado sin duplicar.
 * Si la persona corrige algo, el contenido cambia y se genera una clave nueva.
 */
export function useClaveIdempotente(contenido) {
  const huella = JSON.stringify(contenido)
  const [estado, setEstado] = useState(() => ({ huella, clave: nueva() }))

  // Ajuste de estado durante el render (patrón de React): sin efecto y sin render de más.
  if (estado.huella !== huella) setEstado({ huella, clave: nueva() })

  return estado.clave
}
