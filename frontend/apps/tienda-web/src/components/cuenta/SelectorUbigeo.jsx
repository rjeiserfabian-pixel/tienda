'use client'

import { useEffect, useId, useState } from 'react'
import { llamar } from '@/lib/cliente'

const titulo = (texto) => String(texto).toLowerCase().replace(/(^|[\s-])\S/g, (c) => c.toUpperCase())

/**
 * Elige el lugar de entrega: departamento → provincia → distrito.
 * `valor` y `onChange` usan el código de 6 dígitos del distrito (ubigeo INEI); vacío si falta alguno.
 */
export default function SelectorUbigeo({ valor = '', onChange, error }) {
  const id = useId()
  const [departamentos, setDepartamentos] = useState(null)
  const [distritos, setDistritos] = useState([])
  const [departamento, setDepartamento] = useState(valor.slice(0, 2))
  const [provincia, setProvincia] = useState(valor.slice(0, 4))
  const [falloCarga, setFalloCarga] = useState(false)

  useEffect(() => {
    let vigente = true
    llamar('ubigeos')
      .then((d) => vigente && setDepartamentos(d))
      .catch(() => vigente && setFalloCarga(true))
    return () => {
      vigente = false
    }
  }, [])

  useEffect(() => {
    if (provincia.length !== 4) {
      setDistritos([])
      return undefined
    }
    let vigente = true
    llamar(`ubigeos?provincia=${provincia}`)
      .then((d) => vigente && setDistritos(d))
      .catch(() => vigente && setFalloCarga(true))
    return () => {
      vigente = false
    }
  }, [provincia])

  const provincias = departamentos?.find((d) => d.codigo === departamento)?.provincias ?? []

  return (
    <div className="form-fila tres">
      <div className="campo">
        <label htmlFor={`${id}-dep`}>Departamento</label>
        <select
          id={`${id}-dep`}
          value={departamento}
          disabled={!departamentos}
          aria-invalid={error ? 'true' : undefined}
          onChange={(e) => {
            setDepartamento(e.target.value)
            setProvincia('')
            onChange('')
          }}
        >
          <option value="">{departamentos ? 'Elige…' : 'Cargando…'}</option>
          {(departamentos ?? []).map((d) => (
            <option key={d.codigo} value={d.codigo}>
              {titulo(d.nombre)}
            </option>
          ))}
        </select>
      </div>
      <div className="campo">
        <label htmlFor={`${id}-prov`}>Provincia</label>
        <select
          id={`${id}-prov`}
          value={provincia}
          disabled={!departamento}
          aria-invalid={error ? 'true' : undefined}
          onChange={(e) => {
            setProvincia(e.target.value)
            onChange('')
          }}
        >
          <option value="">Elige…</option>
          {provincias.map((p) => (
            <option key={p.codigo} value={p.codigo}>
              {titulo(p.nombre)}
            </option>
          ))}
        </select>
      </div>
      <div className="campo">
        <label htmlFor={`${id}-dis`}>Distrito</label>
        <select
          id={`${id}-dis`}
          value={valor.length === 6 && valor.startsWith(provincia) ? valor : ''}
          disabled={!provincia}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">Elige…</option>
          {distritos.map((d) => (
            <option key={d.codigo} value={d.codigo}>
              {titulo(d.nombre)}
            </option>
          ))}
        </select>
      </div>
      {(error || falloCarga) && (
        <p className="campo-error" id={`${id}-error`} role="alert" style={{ gridColumn: '1 / -1' }}>
          {error || 'No pudimos cargar la lista de lugares. Recarga la página.'}
        </p>
      )}
    </div>
  )
}
