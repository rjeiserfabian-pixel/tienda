import { useState } from 'react'
import { api, erroresDeCampo } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import Interruptor from '../../../shared/components/Interruptor'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useConsultaDocumento } from '../../../shared/hooks/useConsultaDocumento'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useRolesParaSelector } from '../hooks/useCatalogos'

const CORREO = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const MAX_USUARIO = 30

function validar(f, repetir) {
  const e = {}
  if (!f.username.trim()) e.username = 'Ingrese el nombre de usuario.'
  else if (/[@\s]/.test(f.username)) e.username = 'No puede contener espacios ni "@".'
  if (!CORREO.test(f.email)) e.email = 'Ingrese un correo válido.'
  if (!f.nombres.trim()) e.nombres = 'Ingrese los nombres.'
  if (!f.apellidos.trim()) e.apellidos = 'Ingrese los apellidos.'
  if (f.documento_numero && !/^[A-Za-z0-9]{6,15}$/.test(f.documento_numero)) {
    e.documento_numero = 'Use de 6 a 15 letras o números.'
  }
  if (f.telefono && !/^[0-9+()\- ]{6,20}$/.test(f.telefono)) e.telefono = 'Teléfono no válido.'
  if (f.password.length < 10) e.password = 'La contraseña debe tener al menos 10 caracteres.'
  if (repetir !== f.password) e.repetir = 'Las contraseñas no coinciden.'
  if (f.empresa_ids.length === 0) e.empresa_ids = 'Elija al menos una empresa.'
  return e
}

function iniciales(f) {
  return [f.nombres, f.apellidos]
    .map((t) => t.trim()[0]?.toUpperCase())
    .filter(Boolean)
    .join('')
}

/** La política de contraseñas rechaza con una lista de motivos (sin nombre de campo): se muestran bajo la contraseña. */
const motivosDeLaContrasena = (error) => {
  const detalle = error?.response?.data?.error?.detalle
  return Array.isArray(detalle) && detalle.length ? { password: detalle.join(' ') } : {}
}

export default function NuevoUsuarioModal({ onCerrar, onCreado, inicial = {} }) {
  const { empresas, empresaActivaId } = useEmpresas()
  const roles = useRolesParaSelector()
  const { tiene } = usePermisos()
  const { consultando, mensaje, consultar, avisar } = useConsultaDocumento()
  const puedeConsultar = tiene('MANTENIMIENTO.CONSULTAS.USAR', { organizacion: true })
  const [f, setF] = useState(() => ({
    username: '',
    email: '',
    nombres: '',
    apellidos: '',
    documento_numero: '',
    telefono: '',
    password: '',
    cargo: '',
    rol: '',
    activo: true,
    empresa_ids: empresaActivaId ? [empresaActivaId] : [],
    ...inicial, // p. ej. los datos del trabajador al crear su usuario
  }))
  const [repetir, setRepetir] = useState('')
  const [verClave, setVerClave] = useState(false)
  const [errores, setErrores] = useState({})

  const crear = useMutacion({
    mutationFn: (datos) => api.post('/seguridad/usuarios/', datos).then((r) => r.data),
    invalidar: [['usuarios']],
    exito: 'Usuario creado. Deberá cambiar su contraseña al ingresar.',
    alExito: (usuario) => onCreado(usuario),
    avisarError: false,
  })

  const cambiar = (e) => setF((p) => ({ ...p, [e.target.name]: e.target.value }))

  // Completa nombres y apellidos con los datos de RENIEC; se revisan antes de crear el usuario.
  const consultarDni = async () => {
    if (!/^\d{8}$/.test(f.documento_numero)) {
      avisar('Escribe los 8 dígitos del DNI antes de consultar.')
      return
    }
    const datos = await consultar('DNI', f.documento_numero)
    if (datos) setF((p) => ({ ...p, nombres: datos.nombres, apellidos: datos.apellidos }))
  }
  const alternarEmpresa = (id) =>
    setF((p) => ({
      ...p,
      empresa_ids: p.empresa_ids.includes(id) ? p.empresa_ids.filter((x) => x !== id) : [...p.empresa_ids, id],
    }))

  const enviar = (evento) => {
    evento.preventDefault()
    if (crear.isPending) return
    const locales = validar(f, repetir)
    setErrores(locales)
    if (Object.keys(locales).length) return
    crear.mutate(
      { ...f, username: f.username.trim(), rol: f.rol ? Number(f.rol) : null },
      { onError: (error) => setErrores({ general: 'No se pudo crear el usuario.', ...motivosDeLaContrasena(error), ...erroresDeCampo(error) }) },
    )
  }

  const ojo = (
    <button
      type="button"
      className="boton-ojo"
      onClick={() => setVerClave((v) => !v)}
      aria-label={verClave ? 'Ocultar contraseñas' : 'Mostrar contraseñas'}
      aria-pressed={verClave}
    >
      <Icono nombre={verClave ? 'ojoOculto' : 'ojo'} tam={20} />
    </button>
  )

  return (
    <Modal titulo="Nuevo usuario" subtitulo="Completa la información para registrar un nuevo usuario." onCerrar={onCerrar} ancho={1040}>
      <form onSubmit={enviar} noValidate>
        <div className="modal-columnas">
          <aside className="modal-panel">
            <div className="avatar-grande">
              <span className="avatar-aro" aria-hidden="true">
                {iniciales(f) || <Icono nombre="user" tam={56} trazo={1.4} />}
              </span>
            </div>

            <h3>Estado del usuario</h3>
            <Interruptor
              activo={f.activo}
              onCambio={(activo) => setF((p) => ({ ...p, activo }))}
              texto={f.activo ? 'Activo' : 'Inactivo'}
              descripcion={f.activo ? 'El usuario podrá acceder al sistema.' : 'Se crea sin acceso; podrá activarlo después.'}
            />

            <div style={{ marginTop: 16 }}>
              <Campo etiqueta="Rol del usuario" icono="user" tipo="select" error={errores.rol}>
                {(p) => (
                  <select {...p} name="rol" value={f.rol} onChange={cambiar} disabled={roles.isLoading}>
                    <option value="">{roles.isLoading ? 'Cargando…' : 'Sin rol por ahora'}</option>
                    {(roles.data ?? []).map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.nombre}
                      </option>
                    ))}
                  </select>
                )}
              </Campo>
              <Campo etiqueta="Cargo" icono="tags" error={errores.cargo}>
                {(p) => <input {...p} name="cargo" value={f.cargo} onChange={cambiar} placeholder="Ej. Jefe de tienda" maxLength={100} />}
              </Campo>
            </div>

            <fieldset className="grupo" style={{ padding: '8px 14px' }}>
              <legend>
                Acceso a empresas <span className="requerido" style={{ color: 'var(--rojo)' }}>*</span>
              </legend>
              {empresas.map((e) => (
                <label key={e.id} className="casilla">
                  <input type="checkbox" checked={f.empresa_ids.includes(e.id)} onChange={() => alternarEmpresa(e.id)} />
                  {e.razon_social}
                </label>
              ))}
              {errores.empresa_ids && <small role="alert" className="campo-error">{errores.empresa_ids}</small>}
            </fieldset>
          </aside>

          <section className="modal-panel">
            <Campo etiqueta="Usuario" requerido icono="user" error={errores.username} contador={{ actual: f.username.length, max: MAX_USUARIO }}>
              {(p) => (
                <input {...p} name="username" value={f.username} onChange={cambiar} maxLength={MAX_USUARIO} placeholder="Ej. juanperez" autoComplete="off" />
              )}
            </Campo>
            <Campo etiqueta="Correo electrónico" requerido icono="correo" error={errores.email}>
              {(p) => <input {...p} name="email" type="email" value={f.email} onChange={cambiar} placeholder="usuario@empresa.com" autoComplete="off" />}
            </Campo>
            <div className="modal-fila">
              <Campo etiqueta="Nombres" requerido icono="user" error={errores.nombres}>
                {(p) => <input {...p} name="nombres" value={f.nombres} onChange={cambiar} placeholder="Ej. Juan Pérez" maxLength={150} />}
              </Campo>
              <Campo etiqueta="Apellidos" requerido icono="user" error={errores.apellidos}>
                {(p) => <input {...p} name="apellidos" value={f.apellidos} onChange={cambiar} placeholder="Ej. García" maxLength={150} />}
              </Campo>
            </div>
            <div className="modal-fila">
              <Campo
                etiqueta="Documento (DNI)"
                icono="documento"
                error={errores.documento_numero || mensaje.error}
                ayuda={mensaje.ok || undefined}
                derecha={
                  puedeConsultar ? (
                    <button type="button" className="boton-consultar" onClick={consultarDni} disabled={consultando || crear.isPending} title="Completar con los datos de RENIEC">
                      <Icono nombre="buscar" tam={17} /> {consultando ? 'Consultando…' : 'Consultar'}
                    </button>
                  ) : undefined
                }
              >
                {(p) => <input {...p} name="documento_numero" value={f.documento_numero} onChange={cambiar} placeholder="Ej. 12345678" maxLength={15} inputMode="numeric" />}
              </Campo>
              <Campo etiqueta="Teléfono" icono="telefono" error={errores.telefono}>
                {(p) => <input {...p} name="telefono" value={f.telefono} onChange={cambiar} placeholder="Ej. 987 654 321" maxLength={20} inputMode="tel" />}
              </Campo>
            </div>
            <div className="modal-fila">
              <Campo etiqueta="Contraseña temporal" requerido icono="lock" derecha={ojo} error={errores.password} ayuda="El usuario deberá cambiarla en su primer ingreso.">
                {(p) => (
                  <input {...p} name="password" type={verClave ? 'text' : 'password'} value={f.password} onChange={cambiar} placeholder="Mín. 10 caracteres" autoComplete="new-password" />
                )}
              </Campo>
              <Campo etiqueta="Confirmar contraseña" requerido icono="lock" error={errores.repetir}>
                {(p) => (
                  <input {...p} type={verClave ? 'text' : 'password'} value={repetir} onChange={(e) => setRepetir(e.target.value)} placeholder="Repite la contraseña" autoComplete="new-password" />
                )}
              </Campo>
            </div>
          </section>
        </div>

        <div className="modal-aviso">
          <Icono nombre="shield" tam={30} />
          <p style={{ margin: 0 }}>
            <strong>Permisos de acceso</strong>
            Los permisos los define el rol. Podrás agregar más roles o permisos individuales desde la ficha del usuario después de crearlo.
          </p>
        </div>

        {errores.general && (
          <p role="alert" className="campo-error" style={{ marginBottom: 0 }}>
            {errores.general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={crear.isPending}>
            <Icono nombre="cerrar" tam={18} /> Cancelar
          </button>
          <button type="submit" className="primario" disabled={crear.isPending}>
            <Icono nombre="usuarioMas" tam={20} /> {crear.isPending ? 'Creando…' : 'Crear usuario'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
