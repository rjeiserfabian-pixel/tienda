import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { api } from '../../../core/api/client'
import { useAuth } from '../../../core/auth/AuthContext'
import BotonVolver from '../../../shared/components/BotonVolver'
import Avatar from '../../../shared/components/Avatar'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import AvisoLectura from '../../../shared/components/AvisoLectura'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useModoLectura } from '../../../shared/hooks/useModoLectura'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaHora } from '../../../shared/utils/fechas'
import AccesosUsuario from '../components/AccesosUsuario'
import AsignacionesUsuario from '../components/AsignacionesUsuario'
import ExcepcionesUsuario from '../components/ExcepcionesUsuario'
import RestablecerPasswordModal from '../components/RestablecerPasswordModal'
import UsuarioDatos from '../components/UsuarioDatos'

export default function UsuarioDetallePage() {
  const { id } = useParams()
  const { usuario: yo } = useAuth()
  const { tiene } = usePermisos()
  const [confirmando, setConfirmando] = useState(false)
  const [restableciendoMfa, setRestableciendoMfa] = useState(false)
  const [restableciendoClave, setRestableciendoClave] = useState(false)

  const consulta = useQuery({
    queryKey: ['usuarios', 'detalle', id],
    queryFn: ({ signal }) => api.get(`/seguridad/usuarios/${id}/`, { signal }).then((r) => r.data),
  })
  const usuario = consulta.data
  const { hash } = useLocation()

  // Llegar con #datos (lápiz del listado) baja a la sección apenas carga la ficha.
  useEffect(() => {
    if (usuario && hash) document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [usuario, hash])

  const cambiarEstado = useMutacion({
    mutationFn: (accion) => api.post(`/seguridad/usuarios/${id}/${accion}/`).then((r) => r.data),
    invalidar: [['usuarios']],
    alExito: (datos) => {
      setConfirmando(false)
      return datos
    },
  })

  const restablecerMfa = useMutacion({
    mutationFn: () => api.post(`/seguridad/usuarios/${id}/restablecer-mfa/`).then((r) => r.data),
    invalidar: [['usuarios']],
    exito: 'Segundo factor restablecido.',
    alExito: () => setRestableciendoMfa(false),
  })

  const lectura = useModoLectura()
  const permitido = (codigo) => tiene(codigo, { organizacion: true })
  const puede = (codigo) => !lectura && permitido(codigo)
  const esUnoMismo = usuario?.id === yo.id

  const nombre = usuario ? [usuario.nombres, usuario.apellidos].filter(Boolean).join(' ') : ''

  return (
    <main className="listado">
      <BotonVolver ruta="/seguridad/usuarios" texto="Volver a Usuarios" />
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(usuario)} vacio="El usuario no existe.">
        {usuario && (
          <>
            <CabeceraListado
              avatar={<Avatar nombre={nombre || usuario.username} tam={58} />}
              titulo={usuario.username}
              descripcion={`${nombre ? `${nombre} · ` : ''}${usuario.email} · Último acceso: ${fechaHora(usuario.ultimo_acceso, 'nunca')}`}
            >
              <span className={`estado-pildora ${usuario.activo ? 'activo' : 'inactivo'}`}>{usuario.activo ? 'Activo' : 'Inactivo'}</span>
              {usuario.trabajador &&
                (permitido('MANTENIMIENTO.PERSONAL.VER') ? (
                  <Link to={`/mantenimiento/personal/${usuario.trabajador.id}?modo=lectura`} className="pildora" data-tono="azul" title="Ver la ficha del trabajador">
                    Trabajador: {usuario.trabajador.nombre}
                  </Link>
                ) : (
                  <span className="pildora" data-tono="azul">Trabajador: {usuario.trabajador.nombre}</span>
                ))}
              {usuario.debe_cambiar_password && <span className="pildora" data-tono="ambar">Clave temporal</span>}
              <span className="pildora" data-tono={usuario.mfa_activo ? 'verde' : 'gris'}>
                2FA {usuario.mfa_activo ? 'activa' : 'no activa'}
              </span>
              {!esUnoMismo && puede('SEGURIDAD.USUARIOS.RESTABLECER_CLAVE') && (
                <button type="button" className="boton-cabecera" onClick={() => setRestableciendoClave(true)}>
                  <Icono nombre="lock" tam={19} /> Restablecer contraseña
                </button>
              )}
              {usuario.mfa_activo && !esUnoMismo && puede('SEGURIDAD.USUARIOS.EDITAR') && (
                <button type="button" className="boton-cabecera" onClick={() => setRestableciendoMfa(true)}>
                  <Icono nombre="reactivar" tam={19} /> Restablecer 2FA
                </button>
              )}
              {puede('SEGURIDAD.USUARIOS.DESACTIVAR') && !esUnoMismo && (
                usuario.activo ? (
                  <button type="button" className="peligro boton-cabecera" onClick={() => setConfirmando(true)}>
                    <Icono nombre="apagar" tam={19} /> Desactivar
                  </button>
                ) : (
                  <button type="button" className="primario boton-cabecera" disabled={cambiarEstado.isPending} onClick={() => cambiarEstado.mutate('reactivar')}>
                    <Icono nombre="reactivar" tam={19} /> {cambiarEstado.isPending ? 'Reactivando…' : 'Reactivar'}
                  </button>
                )
              )}
            </CabeceraListado>

            {lectura && <AvisoLectura puedeEditar={permitido('SEGURIDAD.USUARIOS.EDITAR')} />}
            <UsuarioDatos
              key={usuario.id + usuario.email + usuario.username}
              usuario={usuario}
              puedeEditar={puede('SEGURIDAD.USUARIOS.EDITAR')}
              puedeCambiarUsuario={puede('SEGURIDAD.USUARIOS.CAMBIAR_USUARIO') && !esUnoMismo}
            />
            <AccesosUsuario usuario={usuario} puedeEditar={puede('SEGURIDAD.USUARIOS.EDITAR') && !esUnoMismo} />
            <AsignacionesUsuario usuario={usuario} puedeEditar={puede('SEGURIDAD.USUARIOS.ASIGNAR_ROL')} />
            <ExcepcionesUsuario usuario={usuario} puedeEditar={puede('SEGURIDAD.USUARIOS.EXCEPCIONES')} />

            {restableciendoClave && <RestablecerPasswordModal usuario={usuario} onCerrar={() => setRestableciendoClave(false)} />}
            {restableciendoMfa && (
              <ConfirmarModal
                titulo="Restablecer verificación en dos pasos"
                mensaje={`Se quitará el segundo factor de ${usuario.username} y se cerrarán sus sesiones. Úselo solo si perdió su dispositivo y confirmó su identidad.`}
                textoConfirmar="Restablecer"
                enviando={restablecerMfa.isPending}
                onConfirmar={() => restablecerMfa.mutate()}
                onCerrar={() => setRestableciendoMfa(false)}
              />
            )}
            {confirmando && (
              <ConfirmarModal
                titulo="Desactivar usuario"
                mensaje={`${usuario.username} no podrá ingresar y se cerrarán todas sus sesiones abiertas. Podrá reactivarlo después.`}
                textoConfirmar="Desactivar"
                enviando={cambiarEstado.isPending}
                onConfirmar={() => cambiarEstado.mutate('desactivar')}
                onCerrar={() => setConfirmando(false)}
              />
            )}
          </>
        )}
      </EstadoConsulta>
    </main>
  )
}
