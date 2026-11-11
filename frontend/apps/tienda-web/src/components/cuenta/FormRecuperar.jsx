'use client'

import Link from 'next/link'
import { useState } from 'react'
import { ErrorTienda, llamar } from '@/lib/cliente'

export default function FormRecuperar() {
  const [correo, setCorreo] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [enviado, setEnviado] = useState(false)
  const [error, setError] = useState(null)

  async function enviar(e) {
    e.preventDefault()
    setError(null)
    setEnviando(true)
    try {
      await llamar('cuenta/recuperar', { metodo: 'POST', cuerpo: { correo: correo.trim() } })
      setEnviado(true)
    } catch (err) {
      setError(err instanceof ErrorTienda ? err.message : 'No pudimos enviar el correo.')
    } finally {
      setEnviando(false)
    }
  }

  if (enviado) {
    return (
      <div className="tarjeta-centrada">
        <h1>Revisa tu correo</h1>
        <p className="sub">
          Si <strong>{correo.trim()}</strong> tiene una cuenta, te enviamos un enlace para crear una contraseña nueva.
        </p>
        <p className="alerta">El enlace vale 1 hora y se usa una sola vez. Si no lo ves, revisa tu carpeta de spam.</p>
        <p className="pie-tarjeta">
          <Link href="/cuenta/ingresar">Volver a ingresar</Link>
        </p>
      </div>
    )
  }

  return (
    <div className="tarjeta-centrada">
      <h1>Recupera tu contraseña</h1>
      <p className="sub">Escribe tu correo y te enviamos un enlace para crear una nueva.</p>
      <form className="form" onSubmit={enviar} noValidate>
        {error && (
          <p className="alerta error" role="alert">
            {error}
          </p>
        )}
        <div className="campo">
          <label htmlFor="rec-correo">Correo</label>
          <input id="rec-correo" type="email" inputMode="email" autoComplete="email" value={correo} onChange={(e) => setCorreo(e.target.value)} maxLength={150} required />
        </div>
        <button type="submit" className="boton grande" disabled={enviando || !correo}>
          {enviando ? 'Enviando…' : 'Enviarme el enlace'}
        </button>
      </form>
      <p className="pie-tarjeta">
        <Link href="/cuenta/ingresar">Volver a ingresar</Link>
      </p>
    </div>
  )
}
