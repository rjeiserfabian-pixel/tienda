import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, erroresDeCampo } from '../../../core/api/client'
import AvisoLectura from '../../../shared/components/AvisoLectura'
import BotonVolver from '../../../shared/components/BotonVolver'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useModoLectura } from '../../../shared/hooks/useModoLectura'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { datosParaEnviar, generoDe } from '../maestros'
import NuevoUsuarioModal from '../../seguridad/components/NuevoUsuarioModal'
import CamposMaestro from './CamposMaestro'

const texto = (v) => (v === null || v === undefined ? '' : String(v)) // ids y booleanos viajan como texto en el formulario
const CAMPOS_EDITABLES = (config) => config.campos.filter((c) => !c.soloAlta).map((c) => c.nombre)

function Formulario({ config, registro, puedeEditar }) {
  const nombres = CAMPOS_EDITABLES(config)
  const [f, setF] = useState(() => Object.fromEntries(nombres.map((n) => [n, texto(registro[n])])))
  const [errores, setErrores] = useState({})

  const guardar = useMutacion({
    mutationFn: (datos) => api.patch(`${config.endpoint}${registro.id}/`, datos).then((r) => r.data),
    invalidar: [[config.clave], ['opciones']],
    exito: 'Datos actualizados.',
    avisarError: false,
  })
  const sinCambios = nombres.every((n) => texto(f[n]) === texto(registro[n]))

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending || sinCambios) return
    const locales = config.validar(f)
    setErrores(locales)
    if (Object.keys(locales).length) return
    guardar.mutate(datosParaEnviar(config, f, { alta: false, registro }), {
      onError: (error) => setErrores({ general: 'No se pudo guardar.', ...erroresDeCampo(error) }),
    })
  }

  return (
    <PanelTarjeta id="datos" icono={config.icono} titulo={`Datos del ${config.singular}`} descripcion="Información de identificación y contacto.">
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={!puedeEditar || guardar.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
          <CamposMaestro
            config={config}
            lectura={!puedeEditar}
            registro={registro}
            valores={f}
            errores={errores}
            deshabilitado={!puedeEditar || guardar.isPending}
            onCambio={(campo, valor) => setF((previo) => ({ ...previo, [campo]: valor }))}
          />
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
    </PanelTarjeta>
  )
}

/** Ficha de un maestro: datos editables, activar/desactivar y eliminar. En consulta no se modifica nada. */
export default function MaestroFicha({ config }) {
  const { id } = useParams()
  const navegar = useNavigate()
  const { hash } = useLocation()
  const { tiene } = usePermisos()
  const lectura = useModoLectura()
  const [eliminando, setEliminando] = useState(false)
  const [creandoUsuario, setCreandoUsuario] = useState(false)

  const consulta = useQuery({
    queryKey: [config.clave, 'detalle', id],
    queryFn: ({ signal }) => api.get(`${config.endpoint}${id}/`, { signal }).then((r) => r.data),
  })
  const registro = consulta.data

  // Llegar con #datos (lápiz del listado) baja a esa sección apenas carga la ficha.
  useEffect(() => {
    if (registro && hash) document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [registro, hash])

  const permitido = (accion) => tiene(`${config.permiso}.${accion}`, { organizacion: config.deOrganizacion })
  const puedeEditar = permitido('EDITAR') && !lectura
  const puedeEliminar = permitido('ELIMINAR') && !lectura

  const cambiarEstado = useMutacion({
    mutationFn: (estado) => api.patch(`${config.endpoint}${id}/`, { estado }).then((r) => r.data),
    invalidar: [[config.clave], ['opciones']],
    exito: 'Estado actualizado.',
  })
  const vincular = useMutacion({
    mutationFn: (usuarioId) => api.patch(`${config.endpoint}${id}/`, { usuario: usuarioId }).then((r) => r.data),
    invalidar: [[config.clave], ['opciones'], ['usuarios']],
    exito: 'Usuario creado y vinculado al trabajador.',
  })
  const eliminar = useMutacion({
    mutationFn: () => api.delete(`${config.endpoint}${id}/`),
    invalidar: [[config.clave], ['opciones']],
    exito: `${config.singular.charAt(0).toUpperCase()}${config.singular.slice(1)} eliminad${generoDe(config).o}.`,
    alExito: () => navegar(config.ruta, { replace: true }),
  })

  const activo = registro?.estado === 'ACTIVO'
  const protegido = Boolean(registro && config.protegido?.(registro)) // p. ej. la lista principal de precios

  return (
    <main className="listado">
      <BotonVolver ruta={config.ruta} texto={`Volver a ${config.titulo}`} />
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(registro)} vacio="El registro no existe.">
        {registro && (
          <>
            <CabeceraListado icono={config.icono} titulo={config.tituloFila(registro)} descripcion={config.subtituloFila(registro)}>
              <span className={`estado-pildora ${activo ? 'activo' : 'inactivo'}`}>{activo ? 'Activo' : 'Inactivo'}</span>
              {puedeEditar && !protegido && (
                <button
                  type="button"
                  className={`${activo ? 'peligro' : 'primario'} boton-cabecera`}
                  disabled={cambiarEstado.isPending}
                  onClick={() => cambiarEstado.mutate(activo ? 'INACTIVO' : 'ACTIVO')}
                >
                  <Icono nombre={activo ? 'apagar' : 'reactivar'} tam={19} />{' '}
                  {cambiarEstado.isPending ? 'Guardando…' : activo ? 'Desactivar' : 'Activar'}
                </button>
              )}
              {config.datosUsuario && puedeEditar && !registro.usuario && tiene('SEGURIDAD.USUARIOS.CREAR', { organizacion: true }) && (
                <button type="button" className="boton-cabecera" onClick={() => setCreandoUsuario(true)}>
                  <Icono nombre="usuarioMas" tam={19} /> Crear usuario
                </button>
              )}
              {puedeEliminar && !protegido && (
                <button type="button" className="peligro boton-cabecera" onClick={() => setEliminando(true)}>
                  <Icono nombre="cerrar" tam={19} /> Eliminar
                </button>
              )}
            </CabeceraListado>

            {lectura && <AvisoLectura puedeEditar={permitido('EDITAR')} />}
            <Formulario key={JSON.stringify(registro)} config={config} registro={registro} puedeEditar={puedeEditar} />

            {creandoUsuario && (
              <NuevoUsuarioModal
                inicial={config.datosUsuario(registro)}
                onCerrar={() => setCreandoUsuario(false)}
                onCreado={(usuario) => {
                  setCreandoUsuario(false)
                  vincular.mutate(usuario.id) // si falla, el usuario queda creado y se avisa para vincularlo a mano
                }}
              />
            )}
            {eliminando && (
              <ConfirmarModal
                titulo={`Eliminar ${config.singular}`}
                mensaje={`¿Eliminar a ${config.tituloFila(registro)}? Dejará de aparecer en las listas y su documento quedará libre. El historial se conserva. Si solo quieres que no se use, mejor desactívalo.`}
                textoConfirmar="Eliminar"
                enviando={eliminar.isPending}
                onConfirmar={() => eliminar.mutate()}
                onCerrar={() => setEliminando(false)}
              />
            )}
          </>
        )}
      </EstadoConsulta>
    </main>
  )
}
