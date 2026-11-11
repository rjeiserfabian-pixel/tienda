import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../../core/api/client'
import Can from '../../../shared/components/Can'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import { MODO_LECTURA } from '../../../shared/hooks/useModoLectura'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { ESTADOS, generoDe } from '../maestros'
import ImportarModal from './ImportarModal'
import MaestroModal from './MaestroModal'

/** Lista de un maestro (clientes, proveedores, personal): búsqueda, filtros, tabla y paginación. */
export default function MaestroListado({ config }) {
  const { tiene } = usePermisos()
  const { empresas, empresaActivaId } = useEmpresas()
  const puedeEditar = tiene(`${config.permiso}.EDITAR`, { organizacion: config.deOrganizacion })
  const [busqueda, setBusqueda] = useState('')
  const [estado, setEstado] = useState('')
  const [filtros, setFiltros] = useState({})
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [creando, setCreando] = useState(false)
  const [importando, setImportando] = useState(false)
  const q = useDebounce(busqueda, 400)

  const consulta = useListado([config.clave], config.endpoint, {
    q,
    estado,
    ...filtros,
    empresa: config.porEmpresa ? empresaActivaId : undefined,
    page: pagina,
    page_size: tamano,
  })
  const sembrar = useMutacion({
    mutationFn: () => api.post(`${config.endpoint}sembrar/`).then((r) => r.data),
    invalidar: [[config.clave], ['opciones']],
    exito: (datos) => config.sembrar?.exito(datos.creadas) ?? 'Listo.',
  })
  const filas = consulta.data?.results ?? []
  const desde = (pagina - 1) * tamano + 1

  const ctx = {
    nombreEmpresa: (id) => {
      const e = empresas.find((x) => x.id === id)
      return e ? e.nombre_comercial || e.razon_social : '—'
    },
  }
  const reiniciar = (cambio) => {
    cambio()
    setPagina(1)
  }

  const Arriba = config.arriba // un panel opcional entre la cabecera y la tabla (p. ej. lo que falta cargar)

  return (
    <main className="listado">
      <CabeceraListado icono={config.icono} titulo={config.titulo} descripcion={config.descripcion}>
        <Buscador valor={busqueda} onCambio={(v) => reiniciar(() => setBusqueda(v))} etiqueta={`Buscar ${config.titulo.toLowerCase()}`} placeholder={config.buscar} />
        {config.filtros.map((filtro) => (
          <select
            key={filtro.nombre}
            className="boton-cabecera"
            aria-label={filtro.todos}
            value={filtros[filtro.nombre] ?? ''}
            onChange={(e) => reiniciar(() => setFiltros((previo) => ({ ...previo, [filtro.nombre]: e.target.value })))}
          >
            <option value="">{filtro.todos}</option>
            {filtro.opciones.map(([v, texto]) => (
              <option key={v} value={v}>{texto}</option>
            ))}
          </select>
        ))}
        <select className="boton-cabecera" aria-label="Estado" value={estado} onChange={(e) => reiniciar(() => setEstado(e.target.value))}>
          <option value="">Todos los estados</option>
          {ESTADOS.map(([v, texto]) => (
            <option key={v} value={v}>{texto}s</option>
          ))}
        </select>
        {config.importar && (
          <Can permiso={`${config.permiso}.IMPORTAR`} organizacion={config.deOrganizacion}>
            <button type="button" className="boton-cabecera" onClick={() => setImportando(true)}>
              <Icono nombre="importar" tam={20} /> Importar
            </button>
          </Can>
        )}
        {config.sembrar && (
          <Can permiso={`${config.permiso}.CREAR`} organizacion={config.deOrganizacion}>
            <button type="button" className="boton-cabecera" disabled={sembrar.isPending} onClick={() => sembrar.mutate()}>
              <Icono nombre="importar" tam={20} /> {sembrar.isPending ? 'Cargando…' : config.sembrar.texto}
            </button>
          </Can>
        )}
        <Can permiso={`${config.permiso}.CREAR`} organizacion={config.deOrganizacion}>
          <button type="button" className="primario boton-cabecera" onClick={() => setCreando(true)}>
            <Icono nombre="agregar" tam={20} /> {generoDe(config).nuevo} {config.singular}
          </button>
        </Can>
      </CabeceraListado>

      {Arriba && <Arriba />}

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th className="centrado">#</th>
                {config.columnas.map((c) => (
                  <th key={c.titulo}>{c.titulo}</th>
                ))}
                <th>Estado</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && (
                <FilaVacia
                  columnas={config.columnas.length + 3}
                  icono={config.icono}
                  titulo={`No hay ${config.titulo.toLowerCase()} con esos filtros`}
                  descripcion={`Cambia la búsqueda o crea un${generoDe(config).o} con el botón «${generoDe(config).nuevo} ${config.singular}».`}
                />
              )}
              {filas.map((r, i) => (
                <tr key={r.id}>
                  <td className="centrado celda-suave">{desde + i}</td>
                  {config.columnas.map((c) => (
                    <td key={c.titulo} className={c.suave ? 'celda-suave' : undefined}>{c.celda(r, ctx)}</td>
                  ))}
                  <td>
                    <span className={`estado-pildora ${r.estado === 'ACTIVO' ? 'activo' : 'inactivo'}`}>
                      {r.estado === 'ACTIVO' ? 'Activo' : 'Inactivo'}
                    </span>
                  </td>
                  <td className="centrado">
                    <span className="acciones-fila">
                      <Link to={`${config.ruta}/${r.id}${MODO_LECTURA}`} className="accion-icono ver" aria-label={`Ver a ${config.tituloFila(r)}`} title="Ver (solo consulta)">
                        <Icono nombre="ojo" tam={19} />
                      </Link>
                      {puedeEditar && (
                        <Link to={`${config.ruta}/${r.id}#datos`} className="accion-icono editar" aria-label={`Editar a ${config.tituloFila(r)}`} title="Editar">
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
      {importando && <ImportarModal config={config} onCerrar={() => setImportando(false)} />}
      {creando && <MaestroModal config={config} onCerrar={() => setCreando(false)} />}
    </main>
  )
}
