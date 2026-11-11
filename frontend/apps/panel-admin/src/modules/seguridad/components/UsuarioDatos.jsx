import { useState } from 'react'
import { api, erroresDeCampo } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useMutacion } from '../../../shared/hooks/useMutacion'

const CORREO = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

/** Datos personales. `puedeEditar` solo oculta el botón: el backend vuelve a verificar. */
export default function UsuarioDatos({ usuario, puedeEditar, puedeCambiarUsuario = false }) {
  const [f, setF] = useState({
    username: usuario.username,
    nombres: usuario.nombres,
    apellidos: usuario.apellidos,
    email: usuario.email,
    telefono: usuario.telefono,
    documento_numero: usuario.documento_numero,
  })
  const [errores, setErrores] = useState({})
  const [confirmando, setConfirmando] = useState(false)

  const guardar = useMutacion({
    mutationFn: (datos) => api.patch(`/seguridad/usuarios/${usuario.id}/`, datos).then((r) => r.data),
    invalidar: [['usuarios']],
    exito: 'Datos actualizados.',
    avisarError: false,
  })

  // El ejemplo en gris solo sirve para escribir; en consulta un campo vacío dice que no hay dato.
  const ej = (texto) => (puedeEditar ? texto : 'No registrado')

  const cambiar = (e) => setF((p) => ({ ...p, [e.target.name]: e.target.value }))
  const sinCambios = Object.keys(f).every((k) => f[k] === usuario[k])
  const cambiaUsuario = puedeCambiarUsuario && f.username !== usuario.username

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending || sinCambios) return
    if (!CORREO.test(f.email)) return setErrores({ email: 'Ingrese un correo válido.' })
    if (cambiaUsuario) {
      if (!f.username.trim()) return setErrores({ username: 'Ingrese el nombre de usuario.' })
      if (/[@\s]/.test(f.username)) return setErrores({ username: 'No puede contener espacios ni "@".' })
    }
    setErrores({})
    if (cambiaUsuario) return setConfirmando(true) // cambia con qué nombre entra la persona: se confirma
    enviarCambios()
  }

  const enviarCambios = () => {
    // El nombre de usuario solo viaja si cambió (y el backend exige además el permiso).
    const { username, ...resto } = f
    guardar.mutate(cambiaUsuario ? { ...resto, username: username.trim() } : resto, {
      onSuccess: () => setConfirmando(false),
      onError: (error) => {
        setConfirmando(false)
        setErrores({ general: 'No se pudo guardar.', ...erroresDeCampo(error) })
      },
    })
  }

  return (
    <PanelTarjeta id="datos" icono="user" titulo="Datos del usuario" descripcion="Información personal y de contacto.">
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={!puedeEditar || guardar.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
          <Campo
            etiqueta="Usuario"
            icono="user"
            error={errores.username}
            ayuda={
              puedeCambiarUsuario
                ? 'Es con lo que la persona inicia sesión. Si lo cambias, deberá usar el nuevo.'
                : puedeEditar
                  ? 'Solo quien tiene el permiso puede cambiarlo, y no en la propia cuenta.'
                  : undefined
            }
          >
            {(p) => <input {...p} placeholder={ej('Ej. juanperez')} name="username" value={f.username} maxLength={150} readOnly={!puedeCambiarUsuario} onChange={cambiar} />}
          </Campo>
          <div className="modal-fila">
            <Campo etiqueta="Nombres" icono="user" error={errores.nombres}>
              {(p) => <input {...p} placeholder={ej('Ej. Juan Pérez')} name="nombres" value={f.nombres} onChange={cambiar} />}
            </Campo>
            <Campo etiqueta="Apellidos" icono="user" error={errores.apellidos}>
              {(p) => <input {...p} placeholder={ej('Ej. García')} name="apellidos" value={f.apellidos} onChange={cambiar} />}
            </Campo>
          </div>
          <Campo etiqueta="Correo" icono="correo" error={errores.email}>
            {(p) => <input {...p} placeholder={ej('usuario@empresa.com')} name="email" type="email" value={f.email} onChange={cambiar} />}
          </Campo>
          <div className="modal-fila">
            <Campo etiqueta="Teléfono" icono="telefono" error={errores.telefono}>
              {(p) => <input {...p} placeholder={ej('Ej. 987 654 321')} name="telefono" value={f.telefono} onChange={cambiar} />}
            </Campo>
            <Campo etiqueta="Documento" icono="documento" error={errores.documento_numero}>
              {(p) => <input {...p} placeholder={ej('Ej. 12345678')} name="documento_numero" value={f.documento_numero} onChange={cambiar} />}
            </Campo>
          </div>
        </fieldset>
        {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
        {puedeEditar && (
          <div className="fila-botones">
            <button type="submit" className="primario boton-cabecera" disabled={guardar.isPending || sinCambios}>
              <Icono nombre="shield" tam={19} /> {guardar.isPending ? 'Guardando…' : 'Guardar cambios'}
            </button>
          </div>
        )}
      </form>
      {confirmando && (
        <ConfirmarModal
          titulo="Cambiar el nombre de usuario"
          mensaje={`${usuario.username} pasará a iniciar sesión como ${f.username.trim()}. Avísale a la persona: con el nombre anterior ya no podrá entrar. Quedará registrado en la auditoría.`}
          textoConfirmar="Cambiar usuario"
          enviando={guardar.isPending}
          onConfirmar={enviarCambios}
          onCerrar={() => setConfirmando(false)}
        />
      )}
    </PanelTarjeta>
  )
}
