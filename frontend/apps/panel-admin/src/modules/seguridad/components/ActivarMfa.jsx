import QRCode from 'qrcode'
import { useEffect, useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import { useAuth } from '../../../core/auth/AuthContext'
import Campo from '../../../shared/components/Campo'
import { useMutacion } from '../../../shared/hooks/useMutacion'

/** Códigos de recuperación: se muestran UNA sola vez (en el servidor solo queda su huella). */
export function CodigosRecuperacion({ codigos, onListo }) {
  const texto = codigos.join('\n')
  const descargar = () => {
    const url = URL.createObjectURL(new Blob([texto], { type: 'text/plain' }))
    const enlace = Object.assign(document.createElement('a'), { href: url, download: 'codigos-recuperacion.txt' })
    enlace.click()
    URL.revokeObjectURL(url)
  }
  return (
    <div role="status">
      <p>
        <strong>Guarde estos códigos en un lugar seguro.</strong> Cada uno sirve una sola vez si pierde
        su celular. No volverán a mostrarse.
      </p>
      <pre style={{ padding: 12, borderRadius: 8 }}>{texto}</pre>
      <div className="acciones" style={{ justifyContent: 'flex-start' }}>
        <button type="button" onClick={() => navigator.clipboard?.writeText(texto)}>Copiar</button>
        <button type="button" onClick={descargar}>Descargar</button>
        <button type="button" className="primario" onClick={onListo}>Ya los guardé</button>
      </div>
    </div>
  )
}

/** Asistente: contraseña → escanear QR → confirmar con un código → guardar códigos. */
export default function ActivarMfa({ onTerminado }) {
  const { renovarSesion } = useAuth()
  const [paso, setPaso] = useState(1)
  const [password, setPassword] = useState('')
  const [codigo, setCodigo] = useState('')
  const [datos, setDatos] = useState(null) // { secreto, uri }
  const [qr, setQr] = useState('')
  const [codigos, setCodigos] = useState([])
  const [errores, setErrores] = useState({})

  useEffect(() => {
    if (!datos) return undefined
    let vigente = true
    QRCode.toDataURL(datos.uri, { margin: 1, width: 200 }).then((url) => vigente && setQr(url))
    return () => {
      vigente = false
    }
  }, [datos])

  const configurar = useMutacion({
    mutationFn: () => api.post('/seguridad/mfa/configurar/', { password }).then((r) => r.data),
    avisarError: false,
    alExito: (respuesta) => {
      setDatos(respuesta)
      setPassword('')
      setPaso(2)
    },
  })
  const confirmar = useMutacion({
    mutationFn: async () => {
      const { data } = await api.post('/seguridad/mfa/confirmar/', { codigo: codigo.trim() })
      await renovarSesion() // el usuario ya figura con el factor activo (quita el bloqueo si era obligatorio)
      return data
    },
    invalidar: [['mfa'], ['usuarios']],
    avisarError: false,
    alExito: (respuesta) => {
      setCodigos(respuesta.codigos_recuperacion)
      setPaso(3)
    },
  })

  const alFallar = (error) => setErrores({ general: mensajeDeError(error), ...erroresDeCampo(error) })

  if (paso === 3) return <CodigosRecuperacion codigos={codigos} onListo={onTerminado} />

  if (paso === 2) {
    return (
      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault()
          if (confirmar.isPending) return
          if (!/^\d{6}$/.test(codigo.trim())) return setErrores({ codigo: 'Ingrese los 6 dígitos.' })
          setErrores({})
          confirmar.mutate(undefined, { onError: alFallar })
        }}
      >
        <p>1. Escanee este código con su aplicación autenticadora (Google Authenticator, Microsoft Authenticator, Authy…).</p>
        {qr ? <img src={qr} alt="Código QR para la aplicación autenticadora" width={200} height={200} /> : <p aria-busy="true">Generando código…</p>}
        <p>
          ¿No puede escanearlo? Escriba esta clave: <code>{datos.secreto}</code>
        </p>
        <Campo etiqueta="2. Escriba el código de 6 dígitos que muestra la aplicación" error={errores.codigo}>
          {(p) => <input {...p} placeholder="Ej. 123456" inputMode="numeric" maxLength={6} autoComplete="one-time-code" value={codigo} onChange={(e) => setCodigo(e.target.value.replace(/\D/g, ''))} />}
        </Campo>
        {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
        <button type="submit" className="primario" disabled={confirmar.isPending}>
          {confirmar.isPending ? 'Verificando…' : 'Activar'}
        </button>
      </form>
    )
  }

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        if (configurar.isPending) return
        if (!password) return setErrores({ password: 'Ingrese su contraseña.' })
        setErrores({})
        configurar.mutate(undefined, { onError: alFallar })
      }}
    >
      <Campo etiqueta="Confirme su contraseña para continuar" error={errores.password}>
        {(p) => <input {...p} placeholder="Tu contraseña actual" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />}
      </Campo>
      {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
      <button type="submit" className="primario" disabled={configurar.isPending}>
        {configurar.isPending ? 'Preparando…' : 'Comenzar'}
      </button>
    </form>
  )
}
