'use client'

import { useRouter } from 'next/navigation'
import { useId, useState } from 'react'
import Icono from '../Icono'
import { extraerToken } from '@/lib/servicio-tecnico'

/**
 * «Consulta el estado de tu equipo»: el cliente escribe el código de su hoja o pega el enlace del QR.
 * Solo se acepta un código con el formato correcto; lo demás no sale del navegador.
 */
export default function ConsultaEstado({ inicial = '' }) {
  const router = useRouter()
  const id = useId()
  const [texto, setTexto] = useState(inicial)
  const [error, setError] = useState(null)
  const [buscando, setBuscando] = useState(false)

  function enviar(e) {
    e.preventDefault()
    const token = extraerToken(texto)
    if (!token) {
      setError('Ese código no parece válido. Escribe el código de tu hoja de ingreso o pega el enlace de su código QR.')
      return
    }
    setError(null)
    setBuscando(true)
    router.push(`/servicio-tecnico/${encodeURIComponent(token)}`)
  }

  return (
    <form className="form st-consulta" onSubmit={enviar} noValidate>
      <div className="campo">
        <label htmlFor={`${id}-codigo`}>Código o enlace de tu hoja de ingreso</label>
        <input
          id={`${id}-codigo`}
          value={texto}
          onChange={(e) => {
            setTexto(e.target.value)
            if (error) setError(null)
          }}
          maxLength={300}
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          inputMode="url"
          placeholder="Ej.: aBc123xYz9_k o el enlace del QR"
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error ? `${id}-error` : `${id}-ayuda`}
          required
        />
        {error ? (
          <p className="campo-error" id={`${id}-error`} role="alert">
            {error}
          </p>
        ) : (
          <p className="campo-ayuda" id={`${id}-ayuda`}>
            Lo encuentras en la hoja que te dimos al dejar tu equipo, junto al código QR.
          </p>
        )}
      </div>
      <div className="form-acciones">
        <button type="submit" className="boton grande" disabled={buscando}>
          <Icono nombre="lupa" tam={18} /> {buscando ? 'Buscando…' : 'Ver el estado de mi equipo'}
        </button>
      </div>
    </form>
  )
}
