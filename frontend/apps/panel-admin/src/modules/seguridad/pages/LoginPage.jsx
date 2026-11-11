import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { mensajeDeError } from '../../../core/api/client'
import { useAuth } from '../../../core/auth/AuthContext'
import { MARCA } from '../../../core/marca'
import AuthLayout, { CampoAuth } from '../components/AuthLayout'
import {
  IconoCandado,
  IconoEscudo,
  IconoFlecha,
  IconoGoogle,
  IconoMicrosoft,
  IconoOjo,
  IconoOjoTachado,
  IconoUsuario,
} from '../components/Iconos'
import PasoMfa from '../components/PasoMfa'

function validar({ identificador, password }) {
  const errores = {}
  if (!identificador.trim()) errores.identificador = 'Ingrese su usuario o correo.'
  if (!password) errores.password = 'Ingrese su contraseña.'
  return errores
}

export default function LoginPage() {
  const { autenticado, iniciarSesion } = useAuth()
  const navegar = useNavigate()
  const ubicacion = useLocation()
  const [formulario, setFormulario] = useState({ identificador: '', password: '', recordar: true })
  const [verClave, setVerClave] = useState(false)
  const [errores, setErrores] = useState({})
  const [errorGeneral, setErrorGeneral] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [desafio, setDesafio] = useState(null)

  const destino = ubicacion.state?.desde?.pathname || '/'

  if (autenticado) return <Navigate to="/" replace />
  if (desafio) {
    return (
      <PasoMfa
        desafio={desafio}
        onCancelar={() => setDesafio(null)}
        onListo={() => navegar(destino, { replace: true })}
      />
    )
  }

  const cambiar = (evento) => {
    const { name, type, value, checked } = evento.target
    setFormulario((previo) => ({ ...previo, [name]: type === 'checkbox' ? checked : value }))
  }

  const enviar = async (evento) => {
    evento.preventDefault()
    if (enviando) return
    const encontrados = validar(formulario)
    setErrores(encontrados)
    setErrorGeneral('')
    if (Object.keys(encontrados).length) return // validación local antes de molestar al servidor

    setEnviando(true)
    try {
      const resultado = await iniciarSesion(formulario)
      if (resultado.mfaRequerido) {
        setDesafio(resultado.desafio)
        setFormulario((previo) => ({ ...previo, password: '' }))
        return
      }
      navegar(destino, { replace: true })
    } catch (error) {
      setErrorGeneral(mensajeDeError(error))
      setFormulario((previo) => ({ ...previo, password: '' }))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <AuthLayout>
      <h1>Bienvenido</h1>
      <p className="auth-subtitulo">{MARCA.bienvenida}</p>

      <form onSubmit={enviar} noValidate>
        <CampoAuth icono={<IconoUsuario />} etiqueta="Usuario o correo" error={errores.identificador}>
          {(p) => (
            <input
              {...p}
              name="identificador"
              placeholder="Usuario o correo"
              autoComplete="username"
              autoFocus
              value={formulario.identificador}
              onChange={cambiar}
              disabled={enviando}
            />
          )}
        </CampoAuth>

        <CampoAuth
          icono={<IconoCandado />}
          etiqueta="Contraseña"
          error={errores.password}
          derecha={
            <button
              type="button"
              className="auth-ojo"
              onClick={() => setVerClave((v) => !v)}
              aria-label={verClave ? 'Ocultar contraseña' : 'Mostrar contraseña'}
              aria-pressed={verClave}
            >
              {verClave ? <IconoOjoTachado /> : <IconoOjo />}
            </button>
          }
        >
          {(p) => (
            <input
              {...p}
              name="password"
              type={verClave ? 'text' : 'password'}
              placeholder="Contraseña"
              autoComplete="current-password"
              value={formulario.password}
              onChange={cambiar}
              disabled={enviando}
            />
          )}
        </CampoAuth>

        {errorGeneral && (
          <p role="alert" className="auth-error-general">
            {errorGeneral}
          </p>
        )}

        <button type="submit" className="auth-boton" disabled={enviando}>
          {enviando ? 'Ingresando…' : 'Iniciar sesión'}
          {!enviando && <IconoFlecha tam={24} />}
        </button>

        <div className="auth-opciones">
          <label className="auth-recordar">
            <input type="checkbox" name="recordar" checked={formulario.recordar} onChange={cambiar} disabled={enviando} />
            Mantener sesión activa
          </label>
          <Link to="/recuperar">¿Olvidaste tu contraseña?</Link>
        </div>
      </form>

      <div className="auth-separador">o ingresa con</div>
      <div className="auth-sociales">
        {/* Aún no hay acceso con proveedores externos: se muestran deshabilitados, sin acción falsa. */}
        <button type="button" className="auth-social" disabled title="Disponible próximamente">
          <IconoGoogle />
          Google <small>Pronto</small>
        </button>
        <button type="button" className="auth-social" disabled title="Disponible próximamente">
          <IconoMicrosoft />
          Microsoft <small>Pronto</small>
        </button>
      </div>

      <p className="auth-pie">
        <IconoEscudo tam={30} />
        <span>
          ¿No tienes una cuenta? <strong>Solicítala a tu administrador</strong>
        </span>
      </p>
    </AuthLayout>
  )
}
