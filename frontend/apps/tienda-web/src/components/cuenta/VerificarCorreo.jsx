'use client'

import Link from 'next/link'
import { useEffect, useRef, useState } from 'react'
import { ErrorTienda, llamar } from '@/lib/cliente'
import { useCuenta } from '../Proveedores'

/** Confirma el correo con el token del enlace (va en el fragmento de la dirección, nunca en la query). */
export default function VerificarCorreo() {
  const cuenta = useCuenta()
  const [estado, setEstado] = useState('cargando') // cargando | ok | vencido | sin_enlace | error
  const [mensaje, setMensaje] = useState('')
  const [reenvio, setReenvio] = useState(null)
  const hecho = useRef(false)

  useEffect(() => {
    if (hecho.current) return
    hecho.current = true
    const token = new URLSearchParams(window.location.hash.replace(/^#/, '')).get('token')
    // El token no debe quedar a la vista ni en el historial.
    window.history.replaceState(null, '', window.location.pathname)
    if (!token) {
      setEstado('sin_enlace')
      return
    }
    llamar('cuenta/verificar', { metodo: 'POST', cuerpo: { token } })
      .then(() => {
        setEstado('ok')
        cuenta.recargar()
      })
      .catch((err) => {
        if (err instanceof ErrorTienda && err.codigo === 'enlace_invalido') setEstado('vencido')
        else {
          setMensaje(err instanceof ErrorTienda ? err.message : 'No pudimos confirmar tu correo.')
          setEstado('error')
        }
      })
    // se ejecuta una sola vez
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function reenviar() {
    setReenvio('enviando')
    try {
      await llamar('cuenta/reenviar-verificacion', { metodo: 'POST', cuerpo: {} })
      setReenvio('ok')
    } catch {
      setReenvio('error')
    }
  }

  return (
    <div className="tarjeta-centrada" aria-live="polite">
      {estado === 'cargando' && (
        <>
          <h1>Confirmando tu correo…</h1>
          <p className="sub">Un momento, por favor.</p>
        </>
      )}
      {estado === 'ok' && (
        <>
          <h1>¡Listo, correo confirmado!</h1>
          <p className="sub">Ya puedes comprar con tu cuenta.</p>
          <div className="form-acciones">
            <Link href={cuenta.autenticado ? '/cuenta' : '/cuenta/ingresar'} className="boton">
              {cuenta.autenticado ? 'Ir a mi cuenta' : 'Ingresar'}
            </Link>
            <Link href="/" className="boton secundario">
              Seguir comprando
            </Link>
          </div>
        </>
      )}
      {(estado === 'vencido' || estado === 'sin_enlace') && (
        <>
          <h1>{estado === 'vencido' ? 'Este enlace ya no sirve' : 'Falta el enlace'}</h1>
          <p className="sub">
            {estado === 'vencido'
              ? 'Venció o ya se usó. Puedes pedir uno nuevo.'
              : 'Abre el enlace tal como llegó a tu correo.'}
          </p>
          {cuenta.autenticado ? (
            <>
              {reenvio === 'ok' ? (
                <p className="alerta ok" role="status">
                  Te enviamos un correo nuevo. Revisa tu bandeja y el spam.
                </p>
              ) : (
                <button type="button" className="boton" onClick={reenviar} disabled={reenvio === 'enviando'}>
                  {reenvio === 'enviando' ? 'Enviando…' : 'Enviarme otro enlace'}
                </button>
              )}
              {reenvio === 'error' && (
                <p className="alerta error" role="alert" style={{ marginTop: 12 }}>
                  No pudimos enviarlo. Inténtalo en unos minutos.
                </p>
              )}
            </>
          ) : (
            <Link href="/cuenta/ingresar?volver=/cuenta" className="boton">
              Ingresa para pedir otro enlace
            </Link>
          )}
        </>
      )}
      {estado === 'error' && (
        <>
          <h1>No pudimos confirmar tu correo</h1>
          <p className="alerta error" role="alert">
            {mensaje}
          </p>
        </>
      )}
    </div>
  )
}
