import { useQuery } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useMemo } from 'react'
import { api } from '../../core/api/client'
import { useEmpresas } from './EmpresasContext'

const PermisosContext = createContext(null)

const ORDEN = { PROPIO: 0, ASIGNADO: 1, SUCURSAL: 2, EMPRESA: 3, ORGANIZACION: 4 }
const VACIO = {}

const pedirPermisos = (empresaId, signal) =>
  api
    .get('/seguridad/permisos/mios/', { params: empresaId ? { empresa: empresaId } : {}, signal })
    .then((r) => r.data.permisos)

/**
 * Permisos del usuario en la empresa activa y a nivel de organización.
 * Solo sirve para MOSTRAR u OCULTAR elementos: la autorización real es del backend.
 */
export function PermisosProvider({ children }) {
  const { empresaActivaId } = useEmpresas()

  const empresa = useQuery({
    queryKey: ['permisos', empresaActivaId],
    queryFn: ({ signal }) => pedirPermisos(empresaActivaId, signal),
    enabled: Boolean(empresaActivaId),
    staleTime: 60_000,
  })
  const organizacion = useQuery({
    queryKey: ['permisos', 'organizacion'],
    queryFn: ({ signal }) => pedirPermisos(null, signal),
    staleTime: 60_000,
  })

  const tiene = useCallback(
    (codigo, { organizacion: esDeOrganizacion = false, alcanceMinimo } = {}) => {
      const mapa = (esDeOrganizacion ? organizacion.data : empresa.data) ?? VACIO
      const alcance = mapa[codigo]
      if (!alcance) return false
      return !alcanceMinimo || ORDEN[alcance] >= ORDEN[alcanceMinimo]
    },
    [empresa.data, organizacion.data],
  )

  const valor = useMemo(
    () => ({
      tiene,
      cargando: empresa.isLoading || organizacion.isLoading,
      error: empresa.isError || organizacion.isError,
    }),
    [tiene, empresa.isLoading, organizacion.isLoading, empresa.isError, organizacion.isError],
  )

  return <PermisosContext.Provider value={valor}>{children}</PermisosContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function usePermisos() {
  const contexto = useContext(PermisosContext)
  if (!contexto) throw new Error('usePermisos debe usarse dentro de <PermisosProvider>')
  return contexto
}
