'use client'

import { usePathname, useRouter } from 'next/navigation'
import { useEffect } from 'react'
import { useCuenta } from '../Proveedores'

/**
 * Para páginas privadas: sin sesión manda a ingresar y vuelve aquí después. Devuelve el estado.
 * `omitir` (ref): si vale true no redirige (el cliente acaba de salir a propósito).
 */
export default function useSesionRequerida(omitir) {
  const cuenta = useCuenta()
  const router = useRouter()
  const ruta = usePathname()
  useEffect(() => {
    if (cuenta.estado === 'anonimo' && !omitir?.current) router.replace(`/cuenta/ingresar?volver=${encodeURIComponent(ruta)}`)
  }, [cuenta.estado, ruta, router, omitir])
  return cuenta.estado
}
