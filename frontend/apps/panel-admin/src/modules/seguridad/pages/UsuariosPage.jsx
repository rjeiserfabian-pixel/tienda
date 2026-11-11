import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, mensajeDeError } from '../../../core/api/client'
import { useAuth } from '../../../core/auth/AuthContext'
import Can from '../../../shared/components/Can'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import NuevoUsuarioModal from '../components/NuevoUsuarioModal'
import TablaUsuarios from '../components/TablaUsuarios'
import { useRolesParaSelector } from '../hooks/useCatalogos'
import { exportarUsuarios } from '../exportarUsuarios'

export default function UsuariosPage() {
  const navegar = useNavigate()
  const notificar = useNotificar()
  const { usuario: yo } = useAuth()
  const { tiene } = usePermisos()
  const { empresas } = useEmpresas()
  const roles = useRolesParaSelector()

  const [busqueda, setBusqueda] = useState('')
  const [filtros, setFiltros] = useState({ activo: '', empresa: '', rol: '' })
  const [filtrosAbiertos, setFiltrosAbiertos] = useState(false)
  const [orden, setOrden] = useState('username')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [creando, setCreando] = useState(false)
  const [aDesactivar, setADesactivar] = useState(null)
  const [exportando, setExportando] = useState(false)
  const q = useDebounce(busqueda, 400) // un solo pedido tras dejar de escribir

  const parametros = { q, ...filtros, orden }
  const consulta = useListado(['usuarios'], '/seguridad/usuarios/', { ...parametros, page: pagina, page_size: tamano })
  const filas = consulta.data?.results ?? []

  const cambioDeEstado = useMutacion({
    mutationFn: ({ id, accion }) => api.post(`/seguridad/usuarios/${id}/${accion}/`).then((r) => r.data),
    invalidar: [['usuarios']],
    exito: 'Usuario actualizado.',
    alExito: () => setADesactivar(null),
  })

  const volverAPrimera = (cambio) => (valor) => {
    cambio(valor)
    setPagina(1)
  }
  const cambiarFiltro = (campo) => (e) => {
    setFiltros((previos) => ({ ...previos, [campo]: e.target.value }))
    setPagina(1)
  }
  const alOrdenar = (campo) => {
    setOrden((actual) => (actual === campo ? `-${campo}` : campo))
    setPagina(1)
  }
  const hayFiltros = Object.values(filtros).some(Boolean)
  const filtrando = hayFiltros || busqueda.trim() !== ''
  const limpiarTodo = () => {
    setBusqueda('')
    setFiltros({ activo: '', empresa: '', rol: '' })
    setPagina(1)
  }

  const exportar = async () => {
    if (exportando) return
    setExportando(true)
    try {
      const { total, cortado } = await exportarUsuarios(parametros)
      notificar('exito', cortado ? `Se exportaron los primeros ${total} usuarios (límite de seguridad).` : `Se exportaron ${total} usuarios.`)
    } catch (error) {
      notificar('error', mensajeDeError(error))
    } finally {
      setExportando(false)
    }
  }

  return (
    <main className="listado">
      <CabeceraListado icono="users" titulo="Usuarios del Sistema" descripcion="Gestiona los usuarios que tendrán acceso al sistema.">
        <Buscador valor={busqueda} onCambio={volverAPrimera(setBusqueda)} etiqueta="Buscar usuarios" placeholder="Buscar usuario…" />
        <button type="button" className={`boton-cabecera${filtrosAbiertos || hayFiltros ? ' activo' : ''}`} aria-expanded={filtrosAbiertos} onClick={() => setFiltrosAbiertos((v) => !v)}>
          <Icono nombre="filtro" tam={19} /> Filtros{hayFiltros ? ' •' : ''}
        </button>
        <button type="button" className="boton-cabecera" disabled={exportando} onClick={exportar}>
          <Icono nombre="exportar" tam={19} /> {exportando ? 'Exportando…' : 'Exportar'}
        </button>
        <Can permiso="SEGURIDAD.USUARIOS.CREAR" organizacion>
          <button type="button" className="primario boton-cabecera" onClick={() => setCreando(true)}>
            <Icono nombre="agregar" tam={20} /> Nuevo usuario
          </button>
        </Can>
      </CabeceraListado>

      {filtrosAbiertos && (
        <div className="filtros-panel" role="search">
          <label>
            Estado
            <select value={filtros.activo} onChange={cambiarFiltro('activo')}>
              <option value="">Todos</option>
              <option value="true">Activos</option>
              <option value="false">Inactivos</option>
            </select>
          </label>
          <label>
            Empresa
            <select value={filtros.empresa} onChange={cambiarFiltro('empresa')}>
              <option value="">Todas</option>
              {empresas.map((e) => (
                <option key={e.id} value={e.id}>{e.razon_social}</option>
              ))}
            </select>
          </label>
          <label>
            Rol
            <select value={filtros.rol} onChange={cambiarFiltro('rol')}>
              <option value="">Todos</option>
              {(roles.data ?? []).map((r) => (
                <option key={r.id} value={r.id}>{r.nombre}</option>
              ))}
            </select>
          </label>
          {hayFiltros && (
            <button type="button" onClick={() => { setFiltros({ activo: '', empresa: '', rol: '' }); setPagina(1) }}>
              Limpiar filtros
            </button>
          )}
        </div>
      )}

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <TablaUsuarios
          filas={filas}
          desde={(pagina - 1) * tamano + 1}
          orden={orden}
          alOrdenar={alOrdenar}
          yoId={yo.id}
          puedeDesactivar={tiene('SEGURIDAD.USUARIOS.DESACTIVAR', { organizacion: true })}
          alDesactivar={setADesactivar}
          alReactivar={(u) => cambioDeEstado.mutate({ id: u.id, accion: 'reactivar' })}
          pendienteId={cambioDeEstado.isPending ? cambioDeEstado.variables?.id : null}
          filaVacia={
            <FilaVacia
              columnas={9}
              icono={filtrando ? 'buscar' : 'users'}
              titulo={filtrando ? 'No hay usuarios con esos filtros' : 'Aún no hay usuarios'}
              descripcion={
                filtrando
                  ? 'Prueba con otra búsqueda o quita algún filtro para ver más resultados.'
                  : 'Crea el primero con el botón «Nuevo usuario».'
              }
            >
              {filtrando && (
                <button type="button" onClick={limpiarTodo}>
                  Limpiar búsqueda y filtros
                </button>
              )}
            </FilaVacia>
          }
        />
      </EstadoConsulta>

      <Paginacion
        pagina={pagina}
        tamano={tamano}
        total={consulta.data?.count ?? 0}
        onPagina={setPagina}
        onTamano={(t) => {
          setTamano(t)
          setPagina(1)
        }}
      />

      {creando && (
        <NuevoUsuarioModal onCerrar={() => setCreando(false)} onCreado={(usuario) => navegar(`/seguridad/usuarios/${usuario.id}`)} />
      )}
      {aDesactivar && (
        <ConfirmarModal
          titulo="Desactivar usuario"
          mensaje={`${aDesactivar.username} no podrá ingresar y se cerrarán todas sus sesiones abiertas. Podrá reactivarlo después.`}
          textoConfirmar="Desactivar"
          enviando={cambioDeEstado.isPending}
          onConfirmar={() => cambioDeEstado.mutate({ id: aDesactivar.id, accion: 'desactivar' })}
          onCerrar={() => setADesactivar(null)}
        />
      )}
    </main>
  )
}
