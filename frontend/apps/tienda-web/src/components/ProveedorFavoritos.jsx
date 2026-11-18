'use client'

import { usePathname, useRouter } from 'next/navigation'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { llamar } from '@/lib/cliente'
import { useCuenta } from './Proveedores'

/**
 * Favoritos y «avísame cuando llegue» del cliente. Viven en el servidor (hacen falta para escribirle
 * cuando llegue el producto); aquí solo se guardan los números para pintar los corazones. Quien
 * no tiene sesión es llevado a ingresar y vuelve a la misma página.
 */
const ContextoFavoritos = createContext(null)
export const useFavoritos = () => useContext(ContextoFavoritos)

export default function ProveedorFavoritos({ children }) {
  const cuenta = useCuenta()
  const router = useRouter()
  const ruta = usePathname()
  const autenticado = Boolean(cuenta?.autenticado)
  const [ids, setIds] = useState([])
  const [avisos, setAvisos] = useState([])
  const [ocupado, setOcupado] = useState(false)

  useEffect(() => {
    if (!autenticado) {
      setIds([])
      setAvisos([])
      return undefined
    }
    let vigente = true
    llamar('cuenta/favoritos')
      .then((d) => {
        if (!vigente) return
        setIds(d.ids ?? [])
        setAvisos(d.avisos ?? [])
      })
      .catch(() => {})
    return () => {
      vigente = false
    }
  }, [autenticado])

  const irAIngresar = useCallback(() => router.push(`/cuenta/ingresar?volver=${encodeURIComponent(ruta || '/')}`), [router, ruta])

  const alternar = useCallback(
    async (productoId) => {
      if (!autenticado) return irAIngresar()
      const esta = ids.includes(productoId)
      setIds((l) => (esta ? l.filter((x) => x !== productoId) : [productoId, ...l])) // al instante
      try {
        const d = await llamar(`cuenta/favoritos/${productoId}`, { metodo: esta ? 'DELETE' : 'PUT', cuerpo: esta ? undefined : {} })
        setIds(d.ids ?? [])
      } catch {
        setIds((l) => (esta ? [productoId, ...l] : l.filter((x) => x !== productoId))) // se deshace
      }
      return undefined
    },
    [autenticado, ids, irAIngresar],
  )

  const alternarAviso = useCallback(
    async (productoId) => {
      if (!autenticado) return irAIngresar()
      const esta = avisos.includes(productoId)
      setOcupado(true)
      try {
        const d = await llamar(`cuenta/avisos-stock/${productoId}`, { metodo: esta ? 'DELETE' : 'PUT', cuerpo: esta ? undefined : {} })
        setAvisos(d.avisos ?? [])
        return null
      } catch (e) {
        return e?.message ?? 'No pudimos guardar tu aviso. Inténtalo de nuevo.'
      } finally {
        setOcupado(false)
      }
    },
    [autenticado, avisos, irAIngresar],
  )

  const valor = useMemo(
    () => ({ ids, avisos, ocupado, esFavorito: (id) => ids.includes(id), tieneAviso: (id) => avisos.includes(id), alternar, alternarAviso }),
    [ids, avisos, ocupado, alternar, alternarAviso],
  )
  return <ContextoFavoritos.Provider value={valor}>{children}</ContextoFavoritos.Provider>
}
