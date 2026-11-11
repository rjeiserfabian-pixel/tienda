'use client'

import { useId, useState } from 'react'

/** Campo de contraseña con botón «Mostrar / Ocultar». */
export default function CampoClave({ etiqueta, valor, onChange, autoComplete, error, ayuda, nombre }) {
  const id = useId()
  const [ver, setVer] = useState(false)
  const describe = [ayuda ? `${id}-ayuda` : null, error ? `${id}-error` : null].filter(Boolean).join(' ') || undefined
  return (
    <div className="campo">
      <label htmlFor={id}>{etiqueta}</label>
      <div className="campo-clave">
        <input
          id={id}
          name={nombre}
          type={ver ? 'text' : 'password'}
          value={valor}
          onChange={(e) => onChange(e.target.value)}
          autoComplete={autoComplete}
          maxLength={128}
          required
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={describe}
        />
        <button type="button" onClick={() => setVer((v) => !v)} aria-pressed={ver}>
          {ver ? 'Ocultar' : 'Mostrar'}
        </button>
      </div>
      {ayuda && (
        <span className="campo-ayuda" id={`${id}-ayuda`}>
          {ayuda}
        </span>
      )}
      {error && (
        <span className="campo-error" id={`${id}-error`}>
          {error}
        </span>
      )}
    </div>
  )
}
