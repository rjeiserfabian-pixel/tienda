import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import AuthLayout, { CampoAuth } from '../components/AuthLayout'
import { IconoCandado, IconoFlecha, IconoOjo, IconoOjoTachado } from '../components/Iconos'

// El token viaja en el fragmento (#token=…): no llega a registros del servidor ni a "referers".
const leerToken = () => new URLSearchParams(window.location.hash.slice(1)).get('token') ?? ''

/** Paso 2: elegir la contraseña nueva con el enlace recibido por correo. */
export default function RecuperarConfirmarPage() {
  const navegar = useNavigate()
  const notificar = useNotificar()
  const [token] = useState(leerToken)
  const [f, setF] = useState({ nueva: '', repetir: '', codigo_mfa: '' })
  const [verClave, setVerClave] = useState(false)
  const [errores, setErrores] = useState({})
  const [enviando, setEnviando] = useState(false)

  if (!token) {
    return (
      <AuthLayout>
        <h1>Enlace no válido</h1>
        <p className="auth-texto">El enlace está incompleto o ya se usó. Solicite uno nuevo.</p>
        <p className="auth-pie">
          <Link to="/recuperar">Solicitar otro enlace</Link>
        </p>
      </AuthLayout>
    )
  }

  const cambiar = (campo) => (e) => setF((previo) => ({ ...previo, [campo]: e.target.value }))

  const enviar = async (evento) => {
    evento.preventDefault()
    if (enviando) return
    const locales = {}
    if (f.nueva.length < 10) locales.nueva = 'Use al menos 10 caracteres.'
    if (f.nueva !== f.repetir) locales.repetir = 'Las contraseñas no coinciden.'
    setErrores(locales)
    if (Object.keys(locales).length) return

    setEnviando(true)
    try {
      await api.post('/seguridad/auth/recuperar/confirmar/', {
        token,
        nueva: f.nueva,
        codigo_mfa: f.codigo_mfa.trim(),
      })
      window.history.replaceState(null, '', window.location.pathname) // borra el token de la barra
      notificar('exito', 'Contraseña restablecida. Ya puede iniciar sesión.')
      navegar('/login', { replace: true })
    } catch (falla) {
      setErrores({ general: mensajeDeError(falla), ...erroresDeCampo(falla) })
    } finally {
      setEnviando(false)
    }
  }

  const ojo = (
    <button
      type="button"
      className="auth-ojo"
      onClick={() => setVerClave((v) => !v)}
      aria-label={verClave ? 'Ocultar contraseñas' : 'Mostrar contraseñas'}
      aria-pressed={verClave}
    >
      {verClave ? <IconoOjoTachado /> : <IconoOjo />}
    </button>
  )

  return (
    <AuthLayout>
      <h1>Nueva contraseña</h1>
      <p className="auth-subtitulo">Elija una contraseña de al menos 10 caracteres.</p>
      <form onSubmit={enviar} noValidate>
        <CampoAuth icono={<IconoCandado />} etiqueta="Contraseña nueva" error={errores.nueva} derecha={ojo}>
          {(p) => (
            <input {...p} type={verClave ? 'text' : 'password'} placeholder="Contraseña nueva" autoComplete="new-password" autoFocus value={f.nueva} onChange={cambiar('nueva')} disabled={enviando} />
          )}
        </CampoAuth>
        <CampoAuth icono={<IconoCandado />} etiqueta="Repita la contraseña" error={errores.repetir}>
          {(p) => (
            <input {...p} type={verClave ? 'text' : 'password'} placeholder="Repita la contraseña" autoComplete="new-password" value={f.repetir} onChange={cambiar('repetir')} disabled={enviando} />
          )}
        </CampoAuth>
        <CampoAuth icono={<IconoCandado />} etiqueta="Código de verificación (solo si tiene verificación en dos pasos)" error={errores.codigo_mfa}>
          {(p) => (
            <input {...p} placeholder="Código de verificación (si lo usa)" autoComplete="one-time-code" value={f.codigo_mfa} onChange={cambiar('codigo_mfa')} disabled={enviando} />
          )}
        </CampoAuth>
        {errores.general && (
          <p role="alert" className="auth-error-general">
            {errores.general}
          </p>
        )}
        <button type="submit" className="auth-boton" disabled={enviando}>
          {enviando ? 'Guardando…' : 'Cambiar contraseña'}
          {!enviando && <IconoFlecha tam={22} />}
        </button>
      </form>
    </AuthLayout>
  )
}
