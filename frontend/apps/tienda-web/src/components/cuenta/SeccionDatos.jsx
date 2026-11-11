'use client'

import { useState } from 'react'
import { ErrorTienda, errorDeCampo, llamar } from '@/lib/cliente'
import { useCuenta } from '../Proveedores'

export default function SeccionDatos() {
  const { perfil, setPerfil } = useCuenta()
  const [datos, setDatos] = useState({
    nombres: perfil.nombres,
    apellidos: perfil.apellidos,
    celular: perfil.celular ?? '',
    acepta_ofertas: perfil.acepta_ofertas,
  })
  const [error, setError] = useState(null)
  const [enviando, setEnviando] = useState(false)
  const [guardado, setGuardado] = useState(false)

  const poner = (campo) => (e) => {
    setGuardado(false)
    setDatos((d) => ({ ...d, [campo]: e.target.value }))
  }
  const f = (campo) => errorDeCampo(error, campo)

  async function enviar(e) {
    e.preventDefault()
    setError(null)
    setGuardado(false)
    setEnviando(true)
    try {
      setPerfil(await llamar('cuenta/perfil', { metodo: 'PATCH', cuerpo: datos }))
      setGuardado(true)
    } catch (err) {
      setError(err instanceof ErrorTienda ? err : new ErrorTienda(0, 'error', 'No pudimos guardar tus datos.'))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <>
      <h1>Mis datos</h1>
      <form className="form cta-form" onSubmit={enviar} noValidate>
        {error && !error.campos && (
          <p className="alerta error" role="alert">
            {error.message}
          </p>
        )}
        {guardado && (
          <p className="alerta ok" role="status">
            Guardamos tus datos.
          </p>
        )}
        <div className="campo">
          <label htmlFor="dat-correo">Correo</label>
          <input id="dat-correo" value={perfil.correo} readOnly aria-describedby="dat-correo-ayuda" />
          <span className="campo-ayuda" id="dat-correo-ayuda">
            {perfil.correo_verificado ? 'Correo confirmado.' : 'Aún sin confirmar.'} El correo no se puede cambiar.
          </span>
        </div>
        <div className="form-fila dos">
          <div className="campo">
            <label htmlFor="dat-nombres">Nombres</label>
            <input id="dat-nombres" value={datos.nombres} onChange={poner('nombres')} maxLength={100} autoComplete="given-name" required aria-invalid={f('nombres') ? 'true' : undefined} />
            {f('nombres') && <span className="campo-error">{f('nombres')}</span>}
          </div>
          <div className="campo">
            <label htmlFor="dat-apellidos">Apellidos</label>
            <input id="dat-apellidos" value={datos.apellidos} onChange={poner('apellidos')} maxLength={100} autoComplete="family-name" required aria-invalid={f('apellidos') ? 'true' : undefined} />
            {f('apellidos') && <span className="campo-error">{f('apellidos')}</span>}
          </div>
        </div>
        <div className="campo">
          <label htmlFor="dat-celular">Celular</label>
          <input id="dat-celular" type="tel" inputMode="tel" value={datos.celular} onChange={poner('celular')} maxLength={20} autoComplete="tel" aria-invalid={f('celular') ? 'true' : undefined} />
          {f('celular') && <span className="campo-error">{f('celular')}</span>}
        </div>
        <label className="campo-check">
          <input
            type="checkbox"
            checked={datos.acepta_ofertas}
            onChange={(e) => {
              setGuardado(false)
              setDatos((d) => ({ ...d, acepta_ofertas: e.target.checked }))
            }}
          />
          <span>Quiero recibir ofertas y novedades por correo.</span>
        </label>
        <div className="form-acciones">
          <button type="submit" className="boton" disabled={enviando}>
            {enviando ? 'Guardando…' : 'Guardar cambios'}
          </button>
        </div>
      </form>
    </>
  )
}
