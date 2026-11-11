import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useAuth } from '../../core/auth/AuthContext'

const EmpresasContext = createContext(null)
const CLAVE = 'empresa_activa'

// sessionStorage es solo una comodidad por pestaña: puede fallar o estar vacío.
const leerGuardada = () => {
  try {
    return Number(sessionStorage.getItem(CLAVE)) || null
  } catch {
    return null
  }
}
const guardar = (id) => {
  try {
    sessionStorage.setItem(CLAVE, String(id))
  } catch {
    /* sin almacenamiento disponible: se ignora */
  }
}

/**
 * Empresa que el usuario está VIENDO en pantalla. Es solo contexto de consulta:
 * toda operación de escritura debe enviar su empresa de forma explícita.
 */
export function EmpresasProvider({ children }) {
  const { empresas } = useAuth()
  const [seleccion, setSeleccion] = useState(leerGuardada)

  // Si la empresa guardada ya no está habilitada, se usa la primera disponible.
  const empresaActivaId = useMemo(() => {
    if (empresas.some((e) => e.id === seleccion)) return seleccion
    return empresas[0]?.id ?? null
  }, [empresas, seleccion])

  useEffect(() => {
    if (empresaActivaId) guardar(empresaActivaId)
  }, [empresaActivaId])

  const elegirEmpresa = useCallback((id) => setSeleccion(id), [])

  const valor = useMemo(
    () => ({
      empresas,
      empresaActivaId,
      empresaActiva: empresas.find((e) => e.id === empresaActivaId) ?? null,
      elegirEmpresa,
    }),
    [empresas, empresaActivaId, elegirEmpresa],
  )

  return <EmpresasContext.Provider value={valor}>{children}</EmpresasContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useEmpresas() {
  const contexto = useContext(EmpresasContext)
  if (!contexto) throw new Error('useEmpresas debe usarse dentro de <EmpresasProvider>')
  return contexto
}
