import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, mensajeDeError } from '../../../core/api/client'
import AuthLayout, { CampoAuth } from '../components/AuthLayout'
import { IconoFlecha, IconoUsuario } from '../components/Iconos'

/** Paso 1: pedir el enlace. La respuesta es la misma exista o no la cuenta. */
export default function RecuperarPage() {
  const [identificador, setIdentificador] = useState('')
  const [error, setError] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [enviado, setEnviado] = useState(false)

  const enviar = async (evento) => {
    evento.preventDefault()
    if (enviando) return
    if (!identificador.trim()) return setError('Ingrese su usuario o correo.')
    setError('')
    setEnviando(true)
    try {
      await api.post('/seguridad/auth/recuperar/', { identificador: identificador.trim() })
      setEnviado(true)
    } catch (falla) {
      setError(mensajeDeError(falla))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <AuthLayout>
      <h1>Recuperar acceso</h1>
      {enviado ? (
        <p role="status" className="auth-texto">
          Si la cuenta existe, le enviamos un correo con las instrucciones. El enlace vale por tiempo
          limitado y se usa una sola vez.
        </p>
      ) : (
        <>
          <p className="auth-subtitulo">Ingrese su usuario o correo y le enviaremos un enlace para crear una contraseña nueva.</p>
          <form onSubmit={enviar} noValidate>
            <CampoAuth icono={<IconoUsuario />} etiqueta="Usuario o correo" error={error}>
              {(p) => (
                <input
                  {...p}
                  placeholder="Usuario o correo"
                  autoComplete="username"
                  autoFocus
                  value={identificador}
                  onChange={(e) => setIdentificador(e.target.value)}
                  disabled={enviando}
                />
              )}
            </CampoAuth>
            <button type="submit" className="auth-boton" disabled={enviando}>
              {enviando ? 'Enviando…' : 'Enviar instrucciones'}
              {!enviando && <IconoFlecha tam={22} />}
            </button>
          </form>
        </>
      )}
      <p className="auth-pie">
        <Link to="/login">Volver a iniciar sesión</Link>
      </p>
    </AuthLayout>
  )
}
