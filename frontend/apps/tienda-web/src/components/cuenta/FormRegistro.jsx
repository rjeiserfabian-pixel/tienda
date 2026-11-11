'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { useEffect, useState } from 'react'
import { rutaSegura } from '@/lib/rutas'
import { ErrorTienda, errorDeCampo, llamar } from '@/lib/cliente'
import { useCuenta } from '../Proveedores'
import CampoClave from './CampoClave'

const VACIO = { nombres: '', apellidos: '', celular: '', correo: '', password: '', acepta_terminos: false, acepta_ofertas: false }

export default function FormRegistro() {
  const volver = rutaSegura(useSearchParams().get('volver'))
  const cuenta = useCuenta()
  const [datos, setDatos] = useState(VACIO)
  const [legal, setLegal] = useState({})
  const [error, setError] = useState(null)
  const [enviando, setEnviando] = useState(false)
  const [enviadoA, setEnviadoA] = useState(null)

  useEffect(() => {
    llamar('configuracion')
      .then((c) => setLegal(c?.legal ?? {}))
      .catch(() => {})
  }, [])

  const poner = (campo) => (e) => setDatos((d) => ({ ...d, [campo]: e.target.value }))
  const f = (campo) => errorDeCampo(error, campo)
  const sufijo = volver === '/cuenta' ? '' : `?volver=${encodeURIComponent(volver)}`

  async function enviar(e) {
    e.preventDefault()
    setError(null)
    setEnviando(true)
    try {
      await llamar('cuenta/registro', { metodo: 'POST', cuerpo: { ...datos, correo: datos.correo.trim() } })
      setEnviadoA(datos.correo.trim())
    } catch (err) {
      setError(err instanceof ErrorTienda ? err : new ErrorTienda(0, 'error', 'No pudimos crear tu cuenta.'))
    } finally {
      setEnviando(false)
    }
  }

  if (enviadoA) {
    return (
      <div className="tarjeta-centrada">
        <h1>Revisa tu correo</h1>
        <p className="sub">
          Te enviamos un enlace a <strong>{enviadoA}</strong> para confirmar tu cuenta.
        </p>
        <p className="alerta">Puede tardar un minuto. Si no lo ves, revisa tu carpeta de spam o correo no deseado.</p>
        <div className="form-acciones" style={{ marginTop: 18 }}>
          <Link href={volver === '/cuenta' ? '/' : volver} className="boton secundario">
            Seguir comprando
          </Link>
          <Link href={`/cuenta/ingresar${sufijo}`} className="boton">
            Ya confirmé, ingresar
          </Link>
        </div>
      </div>
    )
  }

  const hayGeneral = error && !error.campos
  const terminos = legal.terminos_url ? (
    <a href={legal.terminos_url} target="_blank" rel="noopener noreferrer" className="enlace">
      términos y condiciones
    </a>
  ) : (
    'términos y condiciones'
  )
  const privacidad = legal.privacidad_url ? (
    <a href={legal.privacidad_url} target="_blank" rel="noopener noreferrer" className="enlace">
      política de privacidad
    </a>
  ) : null

  return (
    <div className="tarjeta-centrada">
      <h1>Crea tu cuenta</h1>
      <p className="sub">Es gratis y te toma un minuto.</p>
      <form className="form" onSubmit={enviar} noValidate>
        {hayGeneral && (
          <p className="alerta error" role="alert">
            {error.message}
          </p>
        )}
        <div className="form-fila dos">
          <div className="campo">
            <label htmlFor="reg-nombres">Nombres</label>
            <input id="reg-nombres" value={datos.nombres} onChange={poner('nombres')} autoComplete="given-name" maxLength={100} required aria-invalid={f('nombres') ? 'true' : undefined} />
            {f('nombres') && <span className="campo-error">{f('nombres')}</span>}
          </div>
          <div className="campo">
            <label htmlFor="reg-apellidos">Apellidos</label>
            <input id="reg-apellidos" value={datos.apellidos} onChange={poner('apellidos')} autoComplete="family-name" maxLength={100} required aria-invalid={f('apellidos') ? 'true' : undefined} />
            {f('apellidos') && <span className="campo-error">{f('apellidos')}</span>}
          </div>
        </div>
        <div className="campo">
          <label htmlFor="reg-celular">
            Celular <span className="campo-opcional">(opcional)</span>
          </label>
          <input id="reg-celular" type="tel" inputMode="tel" value={datos.celular} onChange={poner('celular')} autoComplete="tel" maxLength={20} aria-invalid={f('celular') ? 'true' : undefined} />
          {f('celular') && <span className="campo-error">{f('celular')}</span>}
        </div>
        <div className="campo">
          <label htmlFor="reg-correo">Correo</label>
          <input id="reg-correo" type="email" inputMode="email" value={datos.correo} onChange={poner('correo')} autoComplete="email" maxLength={150} required aria-invalid={f('correo') ? 'true' : undefined} />
          {f('correo') && <span className="campo-error">{f('correo')}</span>}
        </div>
        <CampoClave
          etiqueta="Contraseña"
          valor={datos.password}
          onChange={(v) => setDatos((d) => ({ ...d, password: v }))}
          autoComplete="new-password"
          ayuda="Mínimo 8 caracteres. Evita claves comunes o solo números."
          error={f('password')}
        />
        <label className="campo-check">
          <input type="checkbox" checked={datos.acepta_terminos} onChange={(e) => setDatos((d) => ({ ...d, acepta_terminos: e.target.checked }))} />
          <span>
            Acepto los {terminos}
            {privacidad && <> y la {privacidad}</>}.
          </span>
        </label>
        {f('acepta_terminos') && <span className="campo-error">{f('acepta_terminos')}</span>}
        <label className="campo-check">
          <input type="checkbox" checked={datos.acepta_ofertas} onChange={(e) => setDatos((d) => ({ ...d, acepta_ofertas: e.target.checked }))} />
          <span>Quiero recibir ofertas y novedades por correo (opcional).</span>
        </label>
        <button type="submit" className="boton grande" disabled={enviando || cuenta.autenticado}>
          {enviando ? 'Creando cuenta…' : 'Crear mi cuenta'}
        </button>
      </form>
      <p className="pie-tarjeta">
        ¿Ya tienes cuenta? <Link href={`/cuenta/ingresar${sufijo}`}>Ingresa</Link>
      </p>
    </div>
  )
}
