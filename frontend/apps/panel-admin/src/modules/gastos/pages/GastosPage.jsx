import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import Can from '../../../shared/components/Can'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import { fechaCorta } from '../../almacen/inventario'
import { dinero, ESTADOS_PAGO } from '../gastos'
import '../../almacen/inventario.css'
import '../gastos.css'

const RUTA = '/gastos/registro'
const FILTROS_VACIOS = { categoria: '', con_comprobante: '', pago: '', estado: '', desde: '', hasta: '' }

/** Gastos de la empresa: con y sin comprobante, al contado o por pagar. */
export default function GastosPage() {
  const navegar = useNavigate()
  const { empresaActivaId } = useEmpresas()
  const [busqueda, setBusqueda] = useState('')
  const [params] = useSearchParams()
  const pagoInicial = ['pagado', 'pendiente', 'vencido'].includes(params.get('pago')) ? params.get('pago') : ''
  const [filtros, setFiltros] = useState({ ...FILTROS_VACIOS, pago: pagoInicial })
  const [filtrosAbiertos, setFiltrosAbiertos] = useState(Boolean(pagoInicial))
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const q = useDebounce(busqueda, 400)
  const categorias = useOpciones('/mantenimiento/categorias-gasto/').data ?? []

  const consulta = useListado(['gastos', 'lista'], '/gastos/', { empresa: empresaActivaId, q, ...filtros, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []
  const hayFiltros = Object.values(filtros).some(Boolean)
  const rangoInvalido = filtros.desde && filtros.hasta && filtros.desde > filtros.hasta
  const filtrar = (campo) => (e) => {
    setFiltros((previos) => ({ ...previos, [campo]: e.target.value }))
    setPagina(1)
  }

  return (
    <main className="listado">
      <CabeceraListado icono="coins" titulo="Gastos" descripcion="Luz, alquiler, internet, un taxi… todo lo que la empresa gasta y no revende. Con comprobante o sin él.">
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar gastos"
          placeholder="Detalle, proveedor, número…"
        />
        <button type="button" className={`boton-cabecera${filtrosAbiertos || hayFiltros ? ' activo' : ''}`} aria-expanded={filtrosAbiertos} onClick={() => setFiltrosAbiertos((v) => !v)}>
          <Icono nombre="filtro" tam={19} /> Filtros{hayFiltros ? ' •' : ''}
        </button>
        <Can permiso="GASTOS.REGISTRAR">
          <button type="button" className="primario boton-cabecera" onClick={() => navegar(`${RUTA}/nuevo`)}>
            <Icono nombre="agregar" tam={20} /> Registrar gasto
          </button>
        </Can>
      </CabeceraListado>

      {filtrosAbiertos && (
        <div className="filtros-panel" role="search">
          <label>
            Categoría
            <select value={filtros.categoria} onChange={filtrar('categoria')}>
              <option value="">Todas</option>
              {categorias.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.nombre}
                </option>
              ))}
            </select>
          </label>
          <label>
            Comprobante
            <select value={filtros.con_comprobante} onChange={filtrar('con_comprobante')}>
              <option value="">Con y sin comprobante</option>
              <option value="1">Con comprobante</option>
              <option value="0">Sin comprobante</option>
            </select>
          </label>
          <label>
            Pago
            <select value={filtros.pago} onChange={filtrar('pago')}>
              <option value="">Todos</option>
              <option value="pagado">Pagados</option>
              <option value="pendiente">Por pagar</option>
              <option value="vencido">Vencidos</option>
            </select>
          </label>
          <label>
            Estado
            <select value={filtros.estado} onChange={filtrar('estado')}>
              <option value="">Todos</option>
              <option value="EMITIDO">Vigentes</option>
              <option value="ANULADO">Anulados</option>
            </select>
          </label>
          <label>
            Desde
            <input type="date" value={filtros.desde} onChange={filtrar('desde')} />
          </label>
          <label>
            Hasta
            <input type="date" value={filtros.hasta} onChange={filtrar('hasta')} />
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
          {rangoInvalido && (
            <p role="alert" className="campo-error">
              «Desde» no puede ser posterior a «Hasta».
            </p>
          )}
        </div>
      )}

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Fecha</th>
                <th>N°</th>
                <th>Gasto</th>
                <th>Comprobante</th>
                <th className="num">Total</th>
                <th>Pago</th>
                <th className="centrado">
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={7} icono="coins" titulo="No hay gastos con esos filtros" descripcion="Registra un gasto: con comprobante (luz, alquiler) o sin él (un taxi)." />}
              {filas.map((g) => {
                const pago = ESTADOS_PAGO[g.estado_pago]
                return (
                  <tr key={g.id} className={`fila-clicable${g.estado === 'ANULADO' ? ' anulado' : ''}`} onClick={() => navegar(`${RUTA}/${g.id}`)}>
                    <td>{fechaCorta(g.fecha)}</td>
                    <td className="celda-suave">{String(g.numero).padStart(6, '0')}</td>
                    <td className="col-texto">
                      {g.descripcion}
                      <span className="sub-texto">
                        {g.categoria_nombre}
                        {g.proveedor_nombre ? ` · ${g.proveedor_nombre}` : ''}
                        {!g.con_comprobante && g.gastado_por ? ` · ${g.gastado_por}` : ''}
                        {g.repartido ? ' · Repartido' : ''}
                      </span>
                    </td>
                    <td>
                      {g.con_comprobante ? (
                        <>
                          {g.tipo_comprobante_nombre}
                          <span className="sub-texto">{g.comprobante}</span>
                        </>
                      ) : (
                        <span className="pildora gasto-sin-sustento" data-tono="ambar" title="Sin comprobante: no cuenta como crédito fiscal">
                          Sin comprobante
                        </span>
                      )}
                    </td>
                    <td className="num">{dinero(g.total, g.moneda)}</td>
                    <td>
                      <span className="pildora" data-tono={pago.tono}>
                        {pago.texto}
                      </span>
                      {g.estado_pago === 'VENCIDO' || g.estado_pago === 'PENDIENTE' || g.estado_pago === 'PARCIAL' ? <span className="sub-texto">Vence {fechaCorta(g.fecha_vencimiento)}</span> : null}
                    </td>
                    <td className="centrado">
                      <button
                        type="button"
                        className="accion-icono"
                        aria-label={`Abrir el gasto ${g.numero}`}
                        title="Ver"
                        onClick={(ev) => {
                          ev.stopPropagation()
                          navegar(`${RUTA}/${g.id}`)
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
    </main>
  )
}
