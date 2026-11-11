import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, erroresDeCampo } from '../../../core/api/client'
import BotonVolver from '../../../shared/components/BotonVolver'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import AvisoLectura from '../../../shared/components/AvisoLectura'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useModoLectura } from '../../../shared/hooks/useModoLectura'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import MatrizPermisos from '../components/MatrizPermisos'

function DatosRol({ rol, puedeEditar }) {
  const [f, setF] = useState({ nombre: rol.nombre, descripcion: rol.descripcion })
  const [errores, setErrores] = useState({})
  const guardar = useMutacion({
    mutationFn: (datos) => api.patch(`/seguridad/roles/${rol.id}/`, datos).then((r) => r.data),
    invalidar: [['roles']],
    exito: 'Rol actualizado.',
    avisarError: false,
  })
  const sinCambios = f.nombre === rol.nombre && f.descripcion === rol.descripcion

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending || sinCambios) return
    if (!f.nombre.trim()) return setErrores({ nombre: 'Ingrese el nombre.' })
    setErrores({})
    guardar.mutate(f, { onError: (error) => setErrores({ general: 'No se pudo guardar.', ...erroresDeCampo(error) }) })
  }

  return (
    <form onSubmit={enviar} noValidate style={{ maxWidth: 480 }}>
      <fieldset disabled={!puedeEditar || guardar.isPending} style={{ border: 0, padding: 0 }}>
        <Campo etiqueta="Nombre" icono="tags" error={errores.nombre}>
          {(p) => <input {...p} placeholder={puedeEditar ? 'Ej. Supervisor de tienda' : 'No registrado'} value={f.nombre} onChange={(e) => setF({ ...f, nombre: e.target.value })} />}
        </Campo>
        <Campo etiqueta="Descripción" icono="file" error={errores.descripcion}>
          {(p) => <input {...p} placeholder={puedeEditar ? 'Ej. Supervisa las ventas y atiende reclamos' : 'Sin descripción'} value={f.descripcion} onChange={(e) => setF({ ...f, descripcion: e.target.value })} />}
        </Campo>
      </fieldset>
      {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
      {puedeEditar && (
        <button type="submit" className="primario" disabled={guardar.isPending || sinCambios}>
          {guardar.isPending ? 'Guardando…' : 'Guardar'}
        </button>
      )}
    </form>
  )
}

export default function RolDetallePage() {
  const { id } = useParams()
  const navegar = useNavigate()
  const { tiene } = usePermisos()
  const [eliminando, setEliminando] = useState(false)

  const consulta = useQuery({
    queryKey: ['roles', 'detalle', id],
    queryFn: ({ signal }) => api.get(`/seguridad/roles/${id}/`, { signal }).then((r) => r.data),
  })
  const rol = consulta.data
  const { hash } = useLocation()

  // Llegar con #datos (lápiz del listado) baja a esa sección apenas carga la ficha.
  useEffect(() => {
    if (rol && hash) document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [rol, hash])

  const eliminar = useMutacion({
    mutationFn: () => api.delete(`/seguridad/roles/${id}/`),
    invalidar: [['roles']],
    exito: 'Rol eliminado.',
    alExito: () => navegar('/seguridad/roles', { replace: true }),
  })

  const puedeGestionar = tiene('SEGURIDAD.ROLES.GESTIONAR', { organizacion: true })
  const lectura = useModoLectura()
  const puedeEditar = puedeGestionar && rol && !rol.es_sistema
  const editable = puedeEditar && !lectura

  return (
    <main className="listado">
      <BotonVolver ruta="/seguridad/roles" texto="Volver a Roles y permisos" />
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(rol)} vacio="El rol no existe.">
        {rol && (
          <>
            <CabeceraListado
              icono="key"
              titulo={rol.nombre}
              descripcion={`${rol.codigo} · ${rol.n_usuarios} usuario(s) con este rol · ${Object.keys(rol.permisos).length} permisos`}
            >
              {rol.es_sistema && <span className="pildora" data-tono="ambar">Sistema</span>}
              {rol.es_critico && <span className="pildora" data-tono="rojo">Crítico</span>}
              {editable && (
                <button
                  type="button"
                  className="peligro boton-cabecera"
                  disabled={rol.n_usuarios > 0}
                  title={rol.n_usuarios > 0 ? 'Quite primero las asignaciones del rol' : undefined}
                  onClick={() => setEliminando(true)}
                >
                  <Icono nombre="apagar" tam={19} /> Eliminar rol
                </button>
              )}
            </CabeceraListado>
            {lectura && <AvisoLectura puedeEditar={puedeEditar} />}
            <PanelTarjeta id="datos" icono="tags" titulo="Datos del rol" descripcion="Nombre y descripción que ven los administradores.">
              <DatosRol key={rol.nombre + rol.descripcion} rol={rol} puedeEditar={editable} />
            </PanelTarjeta>
            <MatrizPermisos key={JSON.stringify(rol.permisos)} rol={rol} soloLectura={!editable} />
            {eliminando && (
              <ConfirmarModal
                titulo="Eliminar rol"
                mensaje={`¿Eliminar el rol ${rol.nombre}? Esta acción no se puede deshacer.`}
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
