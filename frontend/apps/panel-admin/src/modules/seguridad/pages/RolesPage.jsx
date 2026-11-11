import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { etiquetaRol } from '../components/etiquetasRol'
import { api, erroresDeCampo } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Can from '../../../shared/components/Can'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import { Icono } from '../../../shared/components/IconosPanel'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import Modal from '../../../shared/components/Modal'
import Paginacion from '../../../shared/components/Paginacion'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { MODO_LECTURA } from '../../../shared/hooks/useModoLectura'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import { useMutacion } from '../../../shared/hooks/useMutacion'

const CODIGO = /^[A-Z][A-Z0-9_]{1,39}$/

function NuevoRolModal({ onCerrar, onCreado }) {
  const [f, setF] = useState({ codigo: '', nombre: '', descripcion: '' })
  const [errores, setErrores] = useState({})

  const crear = useMutacion({
    mutationFn: (datos) => api.post('/seguridad/roles/', datos).then((r) => r.data),
    invalidar: [['roles']],
    exito: 'Rol creado. Ahora defina sus permisos.',
    alExito: onCreado,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (crear.isPending) return
    const codigo = f.codigo.trim().toUpperCase()
    const locales = {}
    if (!CODIGO.test(codigo)) locales.codigo = 'Use mayúsculas, números y guion bajo (2 a 40 caracteres).'
    if (!f.nombre.trim()) locales.nombre = 'Ingrese el nombre.'
    setErrores(locales)
    if (Object.keys(locales).length) return
    crear.mutate(
      { ...f, codigo },
      { onError: (error) => setErrores({ general: 'No se pudo crear el rol.', ...erroresDeCampo(error) }) },
    )
  }

  return (
    <Modal titulo="Nuevo rol" subtitulo="Crea el rol y luego define sus permisos en la matriz." onCerrar={onCerrar}>
      <form onSubmit={enviar} noValidate>
        <Campo etiqueta="Código" icono="tags" error={errores.codigo} ayuda="Identificador estable, p. ej. SUPERVISOR_TIENDA.">
          {(p) => <input {...p} placeholder="Ej. SUPERVISOR_TIENDA" value={f.codigo} onChange={(e) => setF({ ...f, codigo: e.target.value.toUpperCase() })} />}
        </Campo>
        <Campo etiqueta="Nombre" icono="tags" error={errores.nombre}>
          {(p) => <input {...p} placeholder="Ej. Supervisor de tienda" value={f.nombre} onChange={(e) => setF({ ...f, nombre: e.target.value })} />}
        </Campo>
        <Campo etiqueta="Descripción" icono="file" error={errores.descripcion}>
          {(p) => <input {...p} placeholder="Ej. Supervisa las ventas y atiende reclamos" value={f.descripcion} onChange={(e) => setF({ ...f, descripcion: e.target.value })} />}
        </Campo>
        {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={crear.isPending}>Cancelar</button>
          <button type="submit" className="primario" disabled={crear.isPending}>
            {crear.isPending ? 'Creando…' : 'Crear rol'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

export default function RolesPage() {
  const { tiene } = usePermisos()
  const puedeGestionar = tiene('SEGURIDAD.ROLES.GESTIONAR', { organizacion: true })
  const navegar = useNavigate()
  const [busqueda, setBusqueda] = useState('')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [creando, setCreando] = useState(false)
  const q = useDebounce(busqueda, 400)

  const consulta = useListado(['roles'], '/seguridad/roles/', { q, page: pagina, page_size: tamano })
  const filas = consulta.data?.results ?? []

  return (
    <main className="listado">
      <CabeceraListado icono="key" titulo="Roles y permisos" descripcion="Define qué puede hacer cada rol y con qué alcance.">
        <Buscador
          valor={busqueda}
          onCambio={(valor) => {
            setBusqueda(valor)
            setPagina(1)
          }}
          etiqueta="Buscar roles"
          placeholder="Buscar por código o nombre…"
        />
        <Can permiso="SEGURIDAD.ROLES.GESTIONAR" organizacion>
          <button type="button" className="primario boton-cabecera" onClick={() => setCreando(true)}>
            <Icono nombre="agregar" tam={20} /> Nuevo rol
          </button>
        </Can>
      </CabeceraListado>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th className="centrado">#</th>
                <th>Rol</th>
                <th>Descripción</th>
                <th className="centrado">Usuarios</th>
                <th className="centrado">Permisos</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && (
                <FilaVacia columnas={6} icono="key" titulo="No hay roles con ese criterio" descripcion="Prueba con otro código o nombre." />
              )}
              {filas.map((r, i) => (
                <tr key={r.id}>
                  <td className="centrado celda-suave">{(pagina - 1) * tamano + i + 1}</td>
                  <td>
                    <Link to={`/seguridad/roles/${r.id}`} className="celda-usuario">{r.nombre}</Link>
                    <br />
                    <span className="pildora" data-tono={etiquetaRol(r.codigo).tono} style={{ minWidth: 0 }}>{r.codigo}</span>
                    {r.es_sistema && <span className="pildora" data-tono="ambar" style={{ minWidth: 0 }}>Sistema</span>}
                    {r.es_critico && <span className="pildora" data-tono="rojo" style={{ minWidth: 0 }}>Crítico</span>}
                  </td>
                  <td className="celda-suave">{r.descripcion || '—'}</td>
                  <td className="centrado">
                    <span className="pildora" data-tono={r.n_usuarios > 0 ? 'azul' : 'gris'} style={{ minWidth: 40 }}>{r.n_usuarios}</span>
                  </td>
                  <td className="centrado">
                    <span className="pildora" data-tono="gris" style={{ minWidth: 40 }}>{r.n_permisos}</span>
                  </td>
                  <td className="centrado">
                    <span className="acciones-fila">
                      <Link to={`/seguridad/roles/${r.id}${MODO_LECTURA}`} className="accion-icono ver" aria-label={`Ver el rol ${r.nombre}`} title="Ver (solo consulta)">
                        <Icono nombre="ojo" tam={19} />
                      </Link>
                      {puedeGestionar && !r.es_sistema && (
                        <Link to={`/seguridad/roles/${r.id}#datos`} className="accion-icono editar" aria-label={`Editar el rol ${r.nombre}`} title="Editar">
                          <Icono nombre="lapiz" tam={19} />
                        </Link>
                      )}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
      {creando && <NuevoRolModal onCerrar={() => setCreando(false)} onCreado={(rol) => navegar(`/seguridad/roles/${rol.id}`)} />}
    </main>
  )
}
