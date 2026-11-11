import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import Can from '../../../shared/components/Can'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import { Icono } from '../../../shared/components/IconosPanel'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import Paginacion from '../../../shared/components/Paginacion'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { MODO_LECTURA } from '../../../shared/hooks/useModoLectura'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import NuevaEmpresaModal from '../components/NuevaEmpresaModal'

export default function EmpresasPage() {
  const { tiene } = usePermisos()
  const puedeGestionar = tiene('SEGURIDAD.EMPRESAS.GESTIONAR', { organizacion: true })
  const navegar = useNavigate()
  const [busqueda, setBusqueda] = useState('')
  const [estado, setEstado] = useState('')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [creando, setCreando] = useState(false)
  const q = useDebounce(busqueda, 400)

  const consulta = useListado(['empresas'], '/organizacion/empresas/', { q, estado, page: pagina, page_size: tamano })
  const filas = consulta.data?.results ?? []

  return (
    <main className="listado">
      <CabeceraListado icono="building" titulo="Empresas" descripcion="Empresas de la organización, cada una con su RUC.">
        <Buscador
          valor={busqueda}
          onCambio={(valor) => {
            setBusqueda(valor)
            setPagina(1)
          }}
          etiqueta="Buscar empresas"
          placeholder="Buscar por RUC o nombre…"
        />
        <select
          className="boton-cabecera"
          aria-label="Estado"
          value={estado}
          onChange={(e) => {
            setEstado(e.target.value)
            setPagina(1)
          }}
        >
          <option value="">Todos los estados</option>
          <option value="ACTIVO">Activas</option>
          <option value="INACTIVO">Inactivas</option>
          <option value="SUSPENDIDO">Suspendidas</option>
        </select>
        <Can permiso="SEGURIDAD.EMPRESAS.GESTIONAR" organizacion>
          <button type="button" className="primario boton-cabecera" onClick={() => setCreando(true)}>
            <Icono nombre="agregar" tam={20} /> Nueva empresa
          </button>
        </Can>
      </CabeceraListado>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th className="centrado">#</th>
                <th>RUC</th>
                <th>Razón social</th>
                <th>Estado</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && (
                <FilaVacia columnas={5} icono="building" titulo="No hay empresas con esos filtros" descripcion="Cambia la búsqueda o el estado para ver otras empresas." />
              )}
              {filas.map((e, i) => (
                <tr key={e.id}>
                  <td className="centrado celda-suave">{(pagina - 1) * tamano + i + 1}</td>
                  <td className="celda-suave">{e.ruc}</td>
                  <td>
                    <Link to={`/seguridad/empresas/${e.id}`} className="celda-usuario">{e.razon_social}</Link>
                    {e.nombre_comercial && (<><br /><small className="celda-suave">{e.nombre_comercial}</small></>)}
                  </td>
                  <td>
                    <span className={`estado-pildora ${e.estado === 'ACTIVO' ? 'activo' : 'inactivo'}`}>
                      {e.estado === 'ACTIVO' ? 'Activa' : e.estado === 'SUSPENDIDO' ? 'Suspendida' : 'Inactiva'}
                    </span>
                  </td>
                  <td className="centrado">
                    <span className="acciones-fila">
                      <Link to={`/seguridad/empresas/${e.id}${MODO_LECTURA}`} className="accion-icono ver" aria-label={`Ver la empresa ${e.razon_social}`} title="Ver (solo consulta)">
                        <Icono nombre="ojo" tam={19} />
                      </Link>
                      {puedeGestionar && (
                        <Link to={`/seguridad/empresas/${e.id}#datos`} className="accion-icono editar" aria-label={`Editar la empresa ${e.razon_social}`} title="Editar">
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
      {creando && <NuevaEmpresaModal onCerrar={() => setCreando(false)} onCreada={(e) => navegar(`/seguridad/empresas/${e.id}`)} />}
    </main>
  )
}
