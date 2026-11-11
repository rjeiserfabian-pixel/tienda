'use client'

import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { useEffect, useState } from 'react'
import { rutaSegura } from '@/lib/rutas'
import { ErrorTienda } from '@/lib/cliente'
import { useCuenta } from '../Proveedores'
import CampoClave from './CampoClave'

export default function FormIngresar() {
  const router = useRouter()
  const volver = rutaSegura(useSearchParams().get('volver'))
  const cuenta = useCuenta()
  const [correo, setCorreo] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (cuenta.autenticado) router.replace(volver)
  }, [cuenta.autenticado, volver, router])

  async function enviar(e) {
    e.preventDefault()
    setError(null)
    setEnviando(true)
    try {
      await cuenta.ingresar(correo.trim(), password)
      router.replace(volver)
    } catch (err) {
      setError(err instanceof ErrorTienda ? err.message : 'No pudimos ingresar. Inténtalo de nuevo.')
      setEnviando(false)
    }
  }

  const enlace = (ruta) => (volver === '/cuenta' ? ruta : `${ruta}?volver=${encodeURIComponent(volver)}`)

  return (
    <div className="tarjeta-centrada">
      <h1>Ingresa a tu cuenta</h1>
      <p className="sub">Compra más rápido y revisa tus pedidos.</p>
      <form className="form" onSubmit={enviar} noValidate>
        {error && (
          <p className="alerta error" role="alert">
            {error}
          </p>
        )}
        <div className="campo">
          <label htmlFor="ing-correo">Correo</label>
          <input id="ing-correo" type="email" inputMode="email" autoComplete="email" value={correo} onChange={(e) => setCorreo(e.target.value)} maxLength={150} required />
        </div>
        <CampoClave etiqueta="Contraseña" valor={password} onChange={setPassword} autoComplete="current-password" />
        <p className="campo-ayuda">
          <Link href="/cuenta/recuperar" className="enlace">
            Olvidé mi contraseña
          </Link>
        </p>
        <button type="submit" className="boton grande" disabled={enviando || !correo || !password}>
          {enviando ? 'Ingresando…' : 'Ingresar'}
        </button>
      </form>
      <p className="pie-tarjeta">
        ¿Aún no tienes cuenta? <Link href={enlace('/cuenta/registro')}>Crea una gratis</Link>
      </p>
    </div>
  )
}
