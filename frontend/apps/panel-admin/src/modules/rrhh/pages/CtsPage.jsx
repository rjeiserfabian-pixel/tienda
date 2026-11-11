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
import { CalcularCtsModal } from '../components/CtsModales'
import { fechaCorta, soles } from '../rrhh'
import '../rrhh.css'

/** Los cálculos de CTS de la empresa: uno por semestre (mayo y noviembre de cada año). */
export default function CtsPage() {
  const { empresaActivaId } = useEmpresas()
  const navegar = useNavigate()
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(12)
  const [nuevo, setNuevo] = useState(false)
  const consulta = useListado(['cts'], '/rrhh/cts/', { empresa: empresaActivaId, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []

  return (
    <main className="listado">
      <CabeceraListado icono="coins" titulo="CTS" descripcion="Compensación por tiempo de servicios. Se calcula cada semestre (mayo y noviembre) y se registra el depósito a cada trabajador.">
        <Can permiso="RRHH.CTS.CALCULAR">
          <button type="button" className="boton-cabecera primario" onClick={() => setNuevo(true)}>
            <Icono nombre="agregar" tam={19} /> Calcular CTS
          </button>
        </Can>
      </CabeceraListado>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Semestre</th>
                <th>Estado</th>
                <th className="derecha">Trabajadores</th>
                <th className="derecha">Total</th>
                <th>Depositada</th>
                <th className="centrado">Ver</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={6} icono="coins" titulo="Todavía no hay cálculos de CTS" descripcion="Calcula el del último semestre terminado." />}
              {filas.map((c) => (
                <tr key={c.id} className="rh-fila-clicable" onClick={() => navegar(`/rrhh/cts/${c.id}`)}>
                  <td>
                    <strong>
                      {c.periodo_nombre} {c.anio}
                    </strong>
                    <span className="rh-sub">
                      {fechaCorta(c.desde)} al {fechaCorta(c.hasta)}
                    </span>
                  </td>
                  <td>
                    <span className="pildora mas" data-tono={c.estado === 'DEPOSITADO' ? 'verde' : c.num_errores > 0 ? 'rojo' : 'ambar'}>
                      {c.estado === 'DEPOSITADO' ? 'Depositada' : c.num_errores > 0 ? `${c.num_errores} por corregir` : 'En revisión'}
                    </span>
                  </td>
                  <td className="derecha">{c.num_trabajadores}</td>
                  <td className="derecha">
                    <strong>{soles(c.total)}</strong>
                  </td>
                  <td>{c.fecha_deposito ? fechaCorta(c.fecha_deposito) : '—'}</td>
                  <td className="centrado">
                    <span className="acciones-fila">
                      <button
                        type="button"
                        className="accion-icono ver"
                        aria-label={`Ver la CTS de ${c.periodo_nombre} ${c.anio}`}
                        title="Ver el cálculo"
                        onClick={(evento) => {
                          evento.stopPropagation()
                          navegar(`/rrhh/cts/${c.id}`)
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
      {nuevo && <CalcularCtsModal onCerrar={() => setNuevo(false)} onCreado={(c) => navegar(`/rrhh/cts/${c.id}`)} />}
    </main>
  )
}
