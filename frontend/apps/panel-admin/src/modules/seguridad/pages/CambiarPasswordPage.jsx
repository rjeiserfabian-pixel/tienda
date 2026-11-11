import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, erroresDeCampo } from '../../../core/api/client'
import { useAuth } from '../../../core/auth/AuthContext'
import Campo from '../../../shared/components/Campo'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useMutacion } from '../../../shared/hooks/useMutacion'

export default function CambiarPasswordPage() {
  const { usuario, renovarSesion } = useAuth()
  const navegar = useNavigate()
  const [f, setF] = useState({ actual: '', nueva: '', repetir: '' })
  const [ver, setVer] = useState(false)
  const [errores, setErrores] = useState({})

  const cambiar = useMutacion({
    mutationFn: async () => {
      await api.post('/seguridad/auth/cambiar-password/', { actual: f.actual, nueva: f.nueva })
      await renovarSesion() // trae el usuario sin la marca de "clave temporal"
    },
    exito: 'Contraseña actualizada.',
    alExito: () => navegar('/', { replace: true }),
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (cambiar.isPending) return
    const locales = {}
    if (!f.actual) locales.actual = 'Ingrese su contraseña actual.'
    if (f.nueva.length < 10) locales.nueva = 'Use al menos 10 caracteres.'
    if (f.nueva !== f.repetir) locales.repetir = 'Las contraseñas no coinciden.'
    setErrores(locales)
    if (Object.keys(locales).length) return
    cambiar.mutate(undefined, {
      onError: (error) =>
        setErrores({
          general: error?.response?.data?.error?.mensaje ?? 'No se pudo cambiar la contraseña.',
          ...erroresDeCampo(error),
        }),
    })
  }

  const ojo = (
    <button type="button" className="boton-ojo" onClick={() => setVer((v) => !v)} aria-label={ver ? 'Ocultar contraseñas' : 'Mostrar contraseñas'} aria-pressed={ver}>
      <Icono nombre={ver ? 'ojoOculto' : 'ojo'} tam={20} />
    </button>
  )
  const tipo = ver ? 'text' : 'password'
  const poner = (campo) => (e) => setF((previo) => ({ ...previo, [campo]: e.target.value }))

  return (
    <main className="listado">
      <CabeceraListado
        icono="lock"
        titulo="Cambiar contraseña"
        descripcion={usuario.debe_cambiar_password ? 'Tu contraseña es temporal: debes cambiarla para continuar.' : 'Elige una contraseña nueva y segura.'}
      />
      <PanelTarjeta icono="key" titulo="Nueva contraseña" descripcion="Al cambiarla se cerrarán tus otras sesiones abiertas.">
        <form onSubmit={enviar} noValidate className="formulario-ancho">
          <Campo etiqueta="Contraseña actual" requerido icono="lock" error={errores.actual}>
            {(p) => <input {...p} placeholder="Tu contraseña actual" type={tipo} autoComplete="current-password" value={f.actual} onChange={poner('actual')} disabled={cambiar.isPending} />}
          </Campo>
          <Campo etiqueta="Contraseña nueva" requerido icono="lock" derecha={ojo} error={errores.nueva} ayuda="Mínimo 10 caracteres. Evita contraseñas comunes o parecidas a tu usuario.">
            {(p) => <input {...p} placeholder="Mín. 10 caracteres" type={tipo} autoComplete="new-password" value={f.nueva} onChange={poner('nueva')} disabled={cambiar.isPending} />}
          </Campo>
          <Campo etiqueta="Repite la contraseña nueva" requerido icono="lock" error={errores.repetir}>
            {(p) => <input {...p} placeholder="Repite la contraseña nueva" type={tipo} autoComplete="new-password" value={f.repetir} onChange={poner('repetir')} disabled={cambiar.isPending} />}
          </Campo>
          {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
          <div className="fila-botones">
            <button type="submit" className="primario boton-cabecera" disabled={cambiar.isPending}>
              <Icono nombre="shield" tam={19} /> {cambiar.isPending ? 'Guardando…' : 'Cambiar contraseña'}
            </button>
          </div>
        </form>
      </PanelTarjeta>
    </main>
  )
}
