'use client'

import Link from 'next/link'
import { useEffect, useRef, useState } from 'react'
import { ErrorTienda, errorDeCampo, llamar } from '@/lib/cliente'
import CampoClave from './CampoClave'

/** Crear contraseña nueva con el token del enlace (en el fragmento de la dirección). */
export default function FormNuevaClave() {
  const token = useRef(null)
  const [hayToken, setHayToken] = useState(null) // null = aún leyendo
  const [password, setPassword] = useState('')
  const [repetir, setRepetir] = useState('')
  const [error, setError] = useState(null)
  const [enviando, setEnviando] = useState(false)
  const [listo, setListo] = useState(false)

  useEffect(() => {
    const t = new URLSearchParams(window.location.hash.replace(/^#/, '')).get('token')
    window.history.replaceState(null, '', window.location.pathname) // el token no queda en la URL
    token.current = t
    setHayToken(Boolean(t))
  }, [])

  async function enviar(e) {
    e.preventDefault()
    setError(null)
    if (password !== repetir) {
      setError(new ErrorTienda(400, 'datos', 'Las contraseñas no coinciden.', { repetir: ['Las contraseñas no coinciden.'] }))
      return
    }
    setEnviando(true)
    try {
      await llamar('cuenta/recuperar/confirmar', { metodo: 'POST', cuerpo: { token: token.current, password } })
      token.current = null
      setListo(true)
    } catch (err) {
      setError(err instanceof ErrorTienda ? err : new ErrorTienda(0, 'error', 'No pudimos cambiar tu contraseña.'))
    } finally {
      setEnviando(false)
    }
  }

  if (listo) {
    return (
      <div className="tarjeta-centrada">
        <h1>¡Contraseña cambiada!</h1>
        <p className="sub">Por seguridad cerramos tus sesiones abiertas. Ingresa con tu nueva contraseña.</p>
        <Link href="/cuenta/ingresar" className="boton grande">
          Ingresar
        </Link>
      </div>
    )
  }

  if (hayToken === false || error?.codigo === 'enlace_invalido') {
    return (
      <div className="tarjeta-centrada">
        <h1>Este enlace no sirve</h1>
        <p className="sub">Venció, ya se usó o está incompleto. Pide uno nuevo.</p>
        <Link href="/cuenta/recuperar" className="boton grande">
          Pedir otro enlace
        </Link>
      </div>
    )
  }

  const hayGeneral = error && !error.campos
  return (
    <div className="tarjeta-centrada">
      <h1>Crea tu nueva contraseña</h1>
      <p className="sub">Elige una contraseña que no uses en otros sitios.</p>
      <form className="form" onSubmit={enviar} noValidate>
        {hayGeneral && (
          <p className="alerta error" role="alert">
            {error.message}
          </p>
        )}
        <CampoClave
          etiqueta="Contraseña nueva"
          valor={password}
          onChange={setPassword}
          autoComplete="new-password"
          ayuda="Mínimo 8 caracteres. Evita claves comunes o solo números."
          error={errorDeCampo(error, 'password')}
        />
        <CampoClave etiqueta="Repite la contraseña" valor={repetir} onChange={setRepetir} autoComplete="new-password" error={errorDeCampo(error, 'repetir')} />
        <button type="submit" className="boton grande" disabled={enviando || hayToken === null || !password}>
          {enviando ? 'Guardando…' : 'Guardar contraseña'}
        </button>
      </form>
    </div>
  )
}
