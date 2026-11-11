import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import { Icono } from '../../../shared/components/IconosPanel'
import { useMutacion } from '../../../shared/hooks/useMutacion'

const MAX_BYTES = 2 * 1024 * 1024
const TIPOS = ['image/jpeg', 'image/png', 'image/webp']

/** Logo PROPIO de la tienda (distinto del logo de cada empresa). Se sube y se quita al instante. */
export default function LogoTienda({ clave, tieneLogo, version }) {
  const queryClient = useQueryClient()
  const entrada = useRef(null)
  const [vista, setVista] = useState(null)
  const [error, setError] = useState('')

  // La vista previa se pide con sesión (el logo del panel no es público hasta abrir la tienda).
  useEffect(() => {
    if (!tieneLogo) {
      setVista(null)
      return undefined
    }
    const control = new AbortController()
    let direccion = null
    api
      .get('/tienda/admin/logo/', { responseType: 'blob', signal: control.signal })
      .then((r) => {
        direccion = URL.createObjectURL(r.data)
        setVista(direccion)
      })
      .catch(() => {
        if (!control.signal.aborted) setVista(null)
      })
    return () => {
      control.abort()
      if (direccion) URL.revokeObjectURL(direccion)
    }
  }, [tieneLogo, version])

  const alExito = (datos) => queryClient.setQueryData(clave, datos)
  const subir = useMutacion({
    mutationFn: (archivo) => {
      const cuerpo = new FormData()
      cuerpo.append('logo', archivo)
      return api.post('/tienda/admin/logo/', cuerpo).then((r) => r.data)
    },
    exito: 'Logo de la tienda actualizado.',
    alExito,
    avisarError: false,
  })
  const quitar = useMutacion({
    mutationFn: () => api.delete('/tienda/admin/logo/').then((r) => r.data),
    exito: 'Logo de la tienda quitado.',
    alExito,
    avisarError: false,
  })

  const elegir = (evento) => {
    const archivo = evento.target.files?.[0]
    evento.target.value = ''
    if (!archivo) return
    if (!TIPOS.includes(archivo.type)) return setError('Usa una imagen JPG, PNG o WEBP.')
    if (archivo.size > MAX_BYTES) return setError('El logo pesa más de 2 MB.')
    setError('')
    subir.mutate(archivo, { onError: (e) => setError(mensajeDeError(e)) })
  }

  const ocupado = subir.isPending || quitar.isPending
  return (
    <div className="tienda-logo">
      <div className="tienda-logo-vista" aria-live="polite">
        {vista ? <img src={vista} alt="Logo de la tienda" /> : <span className="celda-suave">Sin logo: se muestra el nombre de la tienda.</span>}
      </div>
      <div className="tienda-logo-acciones">
        <input ref={entrada} type="file" accept={TIPOS.join(',')} hidden onChange={elegir} />
        <button type="button" className="boton-cabecera" disabled={ocupado} onClick={() => entrada.current?.click()}>
          <Icono nombre="camara" tam={18} /> {subir.isPending ? 'Subiendo…' : tieneLogo ? 'Cambiar logo' : 'Subir logo'}
        </button>
        {tieneLogo && (
          <button
            type="button"
            className="boton-cabecera"
            disabled={ocupado}
            onClick={() => quitar.mutate(undefined, { onError: (e) => setError(mensajeDeError(e)) })}
          >
            Quitar
          </button>
        )}
        <small className="celda-suave">JPG, PNG o WEBP, hasta 2 MB. Mejor con fondo transparente.</small>
        {error && (
          <p role="alert" className="campo-error">
            {error}
          </p>
        )}
      </div>
    </div>
  )
}
