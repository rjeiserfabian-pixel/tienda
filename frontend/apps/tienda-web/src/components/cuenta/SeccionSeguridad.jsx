'use client'

import { useState } from 'react'
import { ErrorTienda, errorDeCampo, llamar } from '@/lib/cliente'
import CampoClave from './CampoClave'

export default function SeccionSeguridad() {
  const [actual, setActual] = useState('')
  const [nueva, setNueva] = useState('')
  const [repetir, setRepetir] = useState('')
  const [error, setError] = useState(null)
  const [enviando, setEnviando] = useState(false)
  const [listo, setListo] = useState(false)

  async function enviar(e) {
    e.preventDefault()
    setError(null)
    setListo(false)
    if (nueva !== repetir) {
      setError(new ErrorTienda(400, 'datos', 'Las contraseñas no coinciden.', { repetir: ['Las contraseñas no coinciden.'] }))
      return
    }
    setEnviando(true)
    try {
      await llamar('cuenta/cambiar-password', { metodo: 'POST', cuerpo: { actual, nueva } })
      setActual('')
      setNueva('')
      setRepetir('')
      setListo(true)
    } catch (err) {
      setError(err instanceof ErrorTienda ? err : new ErrorTienda(0, 'error', 'No pudimos cambiar tu contraseña.'))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <>
      <h1>Seguridad</h1>
      <p className="cta-sub">Al cambiar tu contraseña cerramos tus sesiones en otros equipos; en este seguirás conectado.</p>
      <form className="form cta-form" onSubmit={enviar} noValidate>
        {error && !error.campos && (
          <p className="alerta error" role="alert">
            {error.message}
          </p>
        )}
        {listo && (
          <p className="alerta ok" role="status">
            Contraseña actualizada. Se cerraron tus otras sesiones.
          </p>
        )}
        <CampoClave etiqueta="Contraseña actual" valor={actual} onChange={setActual} autoComplete="current-password" />
        <CampoClave
          etiqueta="Contraseña nueva"
          valor={nueva}
          onChange={setNueva}
          autoComplete="new-password"
          ayuda="Mínimo 8 caracteres. Evita claves comunes o solo números."
          error={errorDeCampo(error, 'nueva')}
        />
        <CampoClave etiqueta="Repite la contraseña nueva" valor={repetir} onChange={setRepetir} autoComplete="new-password" error={errorDeCampo(error, 'repetir')} />
        <div className="form-acciones">
          <button type="submit" className="boton" disabled={enviando || !actual || !nueva}>
            {enviando ? 'Guardando…' : 'Cambiar contraseña'}
          </button>
        </div>
      </form>
    </>
  )
}
