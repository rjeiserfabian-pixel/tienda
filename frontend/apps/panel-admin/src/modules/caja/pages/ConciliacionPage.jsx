import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../../core/api/client'
import Can from '../../../shared/components/Can'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useListado } from '../../../shared/hooks/useListado'
import { fechaCorta } from '../../almacen/inventario'
import ImportarExtractoModal from '../components/ImportarExtractoModal'
import { dinero, ESTADOS_CONCILIACION } from '../caja'
import '../../almacen/inventario.css'
import '../caja.css'

const FILTROS_VACIOS = { cuenta: '', estado: '' }

/** Estados de cuenta del banco importados y qué tan avanzada está su conciliación. */
export default function ConciliacionPage() {
  const navegar = useNavigate()
  const { empresaActivaId } = useEmpresas()
  const [filtros, setFiltros] = useState(FILTROS_VACIOS)
  const [filtrosAbiertos, setFiltrosAbiertos] = useState(false)
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [importando, setImportando] = useState(false)

  const saldos = useQuery({
    queryKey: ['caja', 'saldos', empresaActivaId],
    queryFn: ({ signal }) => api.get('/caja/saldos/', { params: { empresa: empresaActivaId }, signal }).then((r) => r.data.cuentas),
    enabled: Boolean(empresaActivaId),
  })
  const cuentas = saldos.data ?? []
  const consulta = useListado(['caja', 'extractos'], '/caja/extractos/', { empresa: empresaActivaId, ...filtros, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []
  const hayFiltros = Object.values(filtros).some(Boolean)
  const filtrar = (campo) => (e) => {
    setFiltros((previos) => ({ ...previos, [campo]: e.target.value }))
    setPagina(1)
  }

  return (
    <main className="listado">
      <CabeceraListado icono="scan" titulo="Conciliación bancaria" descripcion="Compara el estado de cuenta del banco con tus movimientos: lo que coincide se une, y lo que el banco cobró y no estaba anotado se registra.">
        <button type="button" className={`boton-cabecera${filtrosAbiertos || hayFiltros ? ' activo' : ''}`} aria-expanded={filtrosAbiertos} onClick={() => setFiltrosAbiertos((v) => !v)}>
          <Icono nombre="filtro" tam={19} /> Filtros{hayFiltros ? ' •' : ''}
        </button>
        <Can permiso="CAJA.CONCILIACION.GESTIONAR">
          <button type="button" className="primario boton-cabecera" onClick={() => setImportando(true)}>
            <Icono nombre="importar" tam={20} /> Importar estado de cuenta
          </button>
        </Can>
      </CabeceraListado>

      {filtrosAbiertos && (
        <div className="filtros-panel" role="search">
          <label>
            Cuenta
            <select value={filtros.cuenta} onChange={filtrar('cuenta')}>
              <option value="">Todas</option>
              {cuentas
                .filter((c) => c.tipo !== 'CAJA')
                .map((c) => (
                  <option key={c.cuenta} value={c.cuenta}>
                    {c.nombre}
                  </option>
                ))}
            </select>
          </label>
          <label>
            Estado
            <select value={filtros.estado} onChange={filtrar('estado')}>
              <option value="">Todos</option>
              <option value="ABIERTO">En proceso</option>
              <option value="CERRADO">Conciliados</option>
            </select>
          </label>
          {hayFiltros && (
            <button
              type="button"
              onClick={() => {
                setFiltros(FILTROS_VACIOS)
                setPagina(1)
              }}
            >
              Limpiar filtros
            </button>
          )}
        </div>
      )}

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>N°</th>
                <th>Cuenta</th>
                <th>Periodo</th>
                <th className="num">Saldo final del banco</th>
                <th className="num">Líneas</th>
                <th className="num">Por conciliar</th>
                <th>Estado</th>
                <th className="centrado">
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={8} icono="scan" titulo="Aún no importaste ningún estado de cuenta" descripcion="Descarga el extracto de tu banco (Excel o CSV) e impórtalo para empezar a conciliar." />}
              {filas.map((e) => {
                const estado = ESTADOS_CONCILIACION[e.estado]
                return (
                  <tr key={e.id} className="fila-clicable" onClick={() => navegar(`/caja/conciliacion/${e.id}`)}>
                    <td className="celda-suave">{String(e.numero).padStart(6, '0')}</td>
                    <td className="col-texto">
                      {e.cuenta_nombre}
                      <span className="sub-texto">{e.archivo_nombre}</span>
                    </td>
                    <td>
                      {fechaCorta(e.desde)} – {fechaCorta(e.hasta)}
                    </td>
                    <td className="num">{e.saldo_final_banco === null ? '—' : dinero(e.saldo_final_banco, e.moneda)}</td>
                    <td className="num">{e.lineas_total}</td>
                    <td className="num">{e.lineas_pendientes}</td>
                    <td>
                      <span className={`estado-pildora ${estado.clase}`}>{estado.texto}</span>
                    </td>
                    <td className="centrado">
                      <button
                        type="button"
                        className="accion-icono"
                        aria-label={`Abrir el estado de cuenta ${e.numero}`}
                        title="Abrir"
                        onClick={(ev) => {
                          ev.stopPropagation()
                          navegar(`/caja/conciliacion/${e.id}`)
                        }}
                      >
                        <Icono nombre="ojo" tam={19} />
                      </button>
                    </td>
                  </tr>
                )
              })}
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

      {importando && <ImportarExtractoModal cuentas={cuentas} onCerrar={() => setImportando(false)} />}
    </main>
  )
}
