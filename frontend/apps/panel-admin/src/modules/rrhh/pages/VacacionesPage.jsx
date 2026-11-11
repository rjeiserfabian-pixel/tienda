import { useState } from 'react'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import VacacionesModal from '../components/VacacionesModal'
import { fechaCorta, numero } from '../rrhh'
import '../rrhh.css'

/** El saldo de vacaciones de cada trabajador: lo ganado, lo tomado y lo que queda. */
export default function VacacionesPage() {
  const { empresaActivaId } = useEmpresas()
  const [busqueda, setBusqueda] = useState('')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [abierto, setAbierto] = useState(null)
  const q = useDebounce(busqueda.trim(), 400)

  const consulta = useListado(['vacaciones'], '/rrhh/vacaciones/saldos/', { empresa: empresaActivaId, q, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []
  // Se busca el trabajador abierto en la lista vigente: así el saldo se actualiza al registrar.
  const actual = abierto && (filas.find((t) => t.personal === abierto) ?? null)

  return (
    <main className="listado">
      <CabeceraListado icono="calendario" titulo="Vacaciones" descripcion="Los días ganados crecen mes a mes según el régimen de cada contrato. Aquí se registran las que toma cada trabajador y se ve cuánto le queda.">
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar trabajador"
          placeholder="Buscar trabajador"
        />
      </CabeceraListado>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Trabajador</th>
                <th>Servicio desde</th>
                <th className="derecha">Días al año</th>
                <th className="derecha">Ganados</th>
                <th className="derecha">Tomados</th>
                <th className="derecha">Saldo</th>
                <th className="centrado">Ver</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={7} icono="calendario" titulo="No hay trabajadores con contrato" descripcion="Registra el contrato en Trabajadores para que aparezcan aquí." />}
              {filas.map((t) => (
                <tr key={t.personal} className="rh-fila-clicable" onClick={() => setAbierto(t.personal)}>
                  <td>
                    <strong>{t.nombre_completo}</strong>
                  </td>
                  <td>{fechaCorta(t.inicio_servicio)}</td>
                  <td className="derecha">{t.dias_anuales}</td>
                  <td className="derecha">{numero(t.ganados)}</td>
                  <td className="derecha">{t.tomados}</td>
                  <td className="derecha">
                    <strong>{numero(t.saldo)}</strong>
                  </td>
                  <td className="centrado">
                    <span className="acciones-fila">
                      <button
                        type="button"
                        className="accion-icono ver"
                        aria-label={`Ver las vacaciones de ${t.nombre_completo}`}
                        title="Ver y registrar vacaciones"
                        onClick={(evento) => {
                          evento.stopPropagation()
                          setAbierto(t.personal)
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
      {actual && <VacacionesModal trabajador={actual} onCerrar={() => setAbierto(null)} />}
    </main>
  )
}
