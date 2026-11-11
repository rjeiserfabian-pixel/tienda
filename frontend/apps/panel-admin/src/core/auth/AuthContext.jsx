import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api, guardarAccess, registrarExpiracion, restaurarSesion } from '../api/client'

const AuthContext = createContext(null)

const SIN_SESION = { usuario: null, organizacion: null, empresas: [] }

function datosDeSesion(data) {
  return {
    usuario: data.usuario,
    organizacion: data.organizacion,
    empresas: data.empresas,
  }
}

export function AuthProvider({ children }) {
  const queryClient = useQueryClient()
  const [sesion, setSesion] = useState(SIN_SESION)
  const [cargando, setCargando] = useState(true)

  const limpiar = useCallback(() => {
    guardarAccess(null)
    queryClient.clear() // nunca queda en memoria lo del usuario anterior (permisos, menú…)
    setSesion(SIN_SESION)
  }, [queryClient])

  // Al abrir la app: intenta recuperar la sesión con la cookie de refresh.
  useEffect(() => {
    registrarExpiracion(limpiar)
    let activo = true
    restaurarSesion()
      .then((data) => activo && setSesion(datosDeSesion(data)))
      .catch(() => activo && setSesion(SIN_SESION))
      .finally(() => activo && setCargando(false))
    return () => {
      activo = false
    }
  }, [limpiar])

  const iniciarSesion = useCallback(async ({ identificador, password, recordar = true }) => {
    const { data } = await api.post('/seguridad/auth/login/', {
      identificador,
      password,
      recordar,
      plataforma: 'WEB',
    })
    // Con segundo factor activo aún NO hay sesión: se devuelve el desafío para el paso 2.
    if (data.mfa_requerido) return { mfaRequerido: true, desafio: data.desafio }
    queryClient.clear()
    guardarAccess(data.access)
    setSesion(datosDeSesion(data))
    return { mfaRequerido: false }
  }, [queryClient])

  const verificarMfa = useCallback(
    async ({ desafio, codigo }) => {
      const { data } = await api.post('/seguridad/auth/mfa/verificar/', { desafio, codigo })
      queryClient.clear()
      guardarAccess(data.access)
      setSesion(datosDeSesion(data))
    },
    [queryClient],
  )

  const cerrarSesion = useCallback(async () => {
    try {
      await api.post('/seguridad/auth/logout/')
    } finally {
      limpiar() // aunque falle la red, la sesión local se descarta
    }
  }, [limpiar])

  // Vuelve a pedir el token (y con él usuario y empresas): hace falta tras crear una empresa,
  // cambiar la contraseña o modificar los accesos propios, porque el token fija las empresas.
  const renovarSesion = useCallback(async () => {
    const data = await restaurarSesion()
    setSesion(datosDeSesion(data))
  }, [])

  const valor = useMemo(
    () => ({
      ...sesion,
      autenticado: Boolean(sesion.usuario),
      cargando,
      iniciarSesion,
      verificarMfa,
      cerrarSesion,
      renovarSesion,
    }),
    [sesion, cargando, iniciarSesion, verificarMfa, cerrarSesion, renovarSesion],
  )

  return <AuthContext.Provider value={valor}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const contexto = useContext(AuthContext)
  if (!contexto) throw new Error('useAuth debe usarse dentro de <AuthProvider>')
  return contexto
}
