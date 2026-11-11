import { useState } from 'react'
import { codigoDeError, mensajeDeError } from '../../../core/api/client'
import { useAuth } from '../../../core/auth/AuthContext'
import AuthLayout, { CampoAuth } from './AuthLayout'
import { IconoCandado, IconoFlecha } from './Iconos'

/** Paso 2 del ingreso: código del autenticador o código de recuperación. */
export default function PasoMfa({ desafio, onCancelar, onListo }) {
  const { verificarMfa } = useAuth()
  const [codigo, setCodigo] = useState('')
  const [error, setError] = useState('')
  const [enviando, setEnviando] = useState(false)

  const enviar = async (evento) => {
    evento.preventDefault()
    if (enviando) return
    if (!codigo.trim()) return setError('Ingrese el código de verificación.')
    setError('')
    setEnviando(true)
    try {
      await verificarMfa({ desafio, codigo: codigo.trim() })
      onListo()
    } catch (falla) {
      setError(mensajeDeError(falla))
      setCodigo('')
      // Si la verificación venció hay que empezar de nuevo.
      if (codigoDeError(falla) === 'desafio_mfa_invalido') onCancelar()
    } finally {
      setEnviando(false)
    }
  }

  return (
    <AuthLayout>
      <h1>Verificación</h1>
      <p className="auth-subtitulo">
        Ingrese el código de 6 dígitos de su aplicación autenticadora, o uno de sus códigos de recuperación.
      </p>
      <form onSubmit={enviar} noValidate>
        <CampoAuth icono={<IconoCandado />} etiqueta="Código de verificación" error={error}>
          {(p) => (
            <input
              {...p}
              placeholder="Código de verificación"
              autoComplete="one-time-code"
              autoFocus
              value={codigo}
              onChange={(e) => setCodigo(e.target.value)}
              disabled={enviando}
            />
          )}
        </CampoAuth>
        <button type="submit" className="auth-boton" disabled={enviando}>
          {enviando ? 'Verificando…' : 'Verificar'}
          {!enviando && <IconoFlecha tam={22} />}
        </button>
        <button type="button" className="auth-boton auth-boton-secundario" onClick={onCancelar} disabled={enviando}>
          Volver
        </button>
      </form>
    </AuthLayout>
  )
}
