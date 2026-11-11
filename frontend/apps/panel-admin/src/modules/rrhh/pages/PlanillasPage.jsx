import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Can from '../../../shared/components/Can'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useListado } from '../../../shared/hooks/useListado'
import PlanillaNuevaModal from '../components/PlanillaNuevaModal'
import { mesAnio, soles } from '../rrhh'
import '../rrhh.css'

/** Las planillas mensuales de la empresa: una por mes, en revisión o cerradas. */
export default function PlanillasPage() {
  const { empresaActivaId } = useEmpresas()
  const navegar = useNavigate()
  const [estado, setEstado] = useState('')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(12)
  const [nueva, setNueva] = useState(false)

  const consulta = useListado(['planillas'], '/rrhh/planillas/', { empresa: empresaActivaId, estado, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []

  return (
    <main className="listado">
      <CabeceraListado icono="calculator" titulo="Planilla" descripcion="Lo que gana y lo que se descuenta cada trabajador, mes a mes. Se prepara con la asistencia y los adelantos, se revisa y se cierra.">
        <select
          className="boton-cabecera"
          aria-label="Estado"
          value={estado}
          onChange={(e) => {
            setEstado(e.target.value)
            setPagina(1)
          }}
        >
          <option value="">Todas</option>
          <option value="BORRADOR">En revisión</option>
          <option value="CERRADA">Cerradas</option>
        </select>
        <Can permiso="RRHH.PLANILLA.CALCULAR">
          <button type="button" className="boton-cabecera primario" onClick={() => setNueva(true)}>
            <Icono nombre="agregar" tam={19} /> Preparar planilla
          </button>
        </Can>
      </CabeceraListado>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Mes</th>
                <th>Estado</th>
                <th className="derecha">Trabajadores</th>
                <th className="derecha">Ingresos</th>
                <th className="derecha">Descuentos</th>
                <th className="derecha">Neto a pagar</th>
                <th className="derecha">EsSalud (empresa)</th>
                <th className="centrado">Ver</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={8} icono="calculator" titulo="Todavía no hay planillas" descripcion="Prepara la del primer mes para empezar." />}
              {filas.map((p) => (
                <tr key={p.id} className="rh-fila-clicable" onClick={() => navegar(`/rrhh/planillas/${p.id}`)}>
                  <td>
                    <strong style={{ textTransform: 'capitalize' }}>{mesAnio(p.periodo)}</strong>
                  </td>
                  <td>
                    <span className="pildora mas" data-tono={p.estado === 'CERRADA' ? 'verde' : p.num_errores > 0 ? 'rojo' : 'ambar'}>
                      {p.estado === 'CERRADA' ? 'Cerrada' : p.num_errores > 0 ? `${p.num_errores} por corregir` : 'En revisión'}
                    </span>
                  </td>
                  <td className="derecha">{p.num_trabajadores}</td>
                  <td className="derecha">{soles(p.total_ingresos)}</td>
                  <td className="derecha">{soles(p.total_descuentos)}</td>
                  <td className="derecha">
                    <strong>{soles(p.total_neto)}</strong>
                  </td>
                  <td className="derecha">{soles(p.total_aportes)}</td>
                  <td className="centrado">
                    <span className="acciones-fila">
                      <button
                        type="button"
                        className="accion-icono ver"
                        aria-label={`Ver la planilla de ${mesAnio(p.periodo)}`}
                        title="Ver la planilla"
                        onClick={(evento) => {
                          evento.stopPropagation()
                          navegar(`/rrhh/planillas/${p.id}`)
                        }}
                      >
                        <Icono nombre="ojo" tam={19} />
                      </button>
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
        onTamano={(n) => {
          setTamano(n)
          setPagina(1)
        }}
      />
      {nueva && <PlanillaNuevaModal onCerrar={() => setNueva(false)} onCreada={(p) => navegar(`/rrhh/planillas/${p.id}`)} />}
    </main>
  )
}
