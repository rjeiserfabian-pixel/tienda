import { useCallback, useEffect, useRef, useState } from 'react'
import { api, mensajeDeError } from '../../core/api/client'

const VACIO = { ok: '', error: '' }

/**
 * Consulta de DNI (RENIEC) o RUC (SUNAT) para autocompletar un formulario.
 * `consultar(tipo, numero)` devuelve los datos o `null` si falló (el motivo queda en `mensaje`).
 * Solo informa: quien lo usa decide qué campos rellenar, y el usuario revisa antes de guardar.
 */
export function useConsultaDocumento() {
  const [consultando, setConsultando] = useState(false)
  const [mensaje, setMensaje] = useState(VACIO)
  const montado = useRef(true)
  useEffect(() => {
    montado.current = true
    return () => {
      montado.current = false
    }
  }, [])

  const consultar = useCallback(async (tipo, numero) => {
    setConsultando(true)
    setMensaje(VACIO)
    try {
      const { data } = await api.get(`/mantenimiento/consultas/${tipo.toLowerCase()}/${numero}/`)
      if (!montado.current) return null
      if (data.es_activo === false) {
        setMensaje({ ok: '', error: `SUNAT: ${data.estado} · ${data.condicion}. Verifica antes de registrarlo.` })
      } else {
        setMensaje({ ok: data.estado ? `SUNAT: ${data.estado} · ${data.condicion}` : 'Datos completados. Revísalos antes de guardar.', error: '' })
      }
      return data
    } catch (error) {
      if (montado.current) setMensaje({ ok: '', error: mensajeDeError(error) })
      return null
    } finally {
      if (montado.current) setConsultando(false)
    }
  }, [])

  const avisar = useCallback((error) => setMensaje({ ok: '', error }), [])
  const limpiar = useCallback(() => setMensaje(VACIO), [])

  return { consultando, mensaje, consultar, avisar, limpiar }
}
