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
import { fechaCorta } from '../../almacen/inventario'
import ConfiguracionOrdenesModal from '../components/ConfiguracionOrdenesModal'
import { dinero, FORMAS_PAGO } from '../compras'
import { ESTADOS_ORDEN } from '../ordenes'
import '../../almacen/inventario.css'

const FILTROS_VACIOS = { estado: '', desde: '', hasta: '', pendientes: '', atrasadas: '' }

/** Órdenes de compra de la empresa activa: lo que se pidió a los proveedores y cuánto ya llegó. */
export default function OrdenesCompraPage() {
  const navegar = useNavigate()
  const { empresaActivaId } = useEmpresas()
  const [busqueda, setBusqueda] = useState('')
  const [params] = useSearchParams()
  const [filtros, setFiltros] = useState(() => ({
    ...FILTROS_VACIOS,
    estado: ESTADOS_ORDEN[params.get('estado')] ? params.get('estado') : '',
    pendientes: params.get('pendientes') === '1' ? '1' : '',
    atrasadas: params.get('atrasadas') === '1' ? '1' : '',
  }))
  const [filtrosAbiertos, setFiltrosAbiertos] = useState(() => Object.values(filtros).some(Boolean))
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [configurando, setConfigurando] = useState(false)
  const q = useDebounce(busqueda, 400)

  const consulta = useListado(['compras', 'ordenes'], '/compras/ordenes/', { empresa: empresaActivaId, q, ...filtros, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []
  const desde = (pagina - 1) * tamano + 1
  const hayFiltros = Object.values(filtros).some(Boolean)
  const rangoInvalido = filtros.desde && filtros.hasta && filtros.desde > filtros.hasta

  const filtrar = (campo) => (e) => {
    setFiltros((previos) => ({ ...previos, [campo]: e.target.value }))
    setPagina(1)
  }
  const marcar = (campo) => (e) => {
    setFiltros((previos) => ({ ...previos, [campo]: e.target.checked ? '1' : '' }))
    setPagina(1)
  }

  return (
    <main className="listado">
      <CabeceraListado icono="checklist" titulo="Órdenes de compra" descripcion="Lo que pediste a tus proveedores y cuánto ya llegó. La mercadería se recibe contra la orden, por partes si hace falta.">
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar órdenes"
          placeholder="Número, proveedor, observación…"
        />
        <button type="button" className={`boton-cabecera${filtrosAbiertos || hayFiltros ? ' activo' : ''}`} aria-expanded={filtrosAbiertos} onClick={() => setFiltrosAbiertos((v) => !v)}>
          <Icono nombre="filtro" tam={19} /> Filtros{hayFiltros ? ' •' : ''}
        </button>
        <Can permiso="ORDENES_COMPRA.CREAR">
          <button type="button" className="boton-cabecera" onClick={() => navegar('/compras/ordenes/reposicion')} title="Qué pedir según el stock mínimo">
            <Icono nombre="boxes" tam={19} /> Reposición
          </button>
        </Can>
        <Can permiso="ORDENES_COMPRA.APROBAR">
          <button type="button" className="boton-cabecera" onClick={() => setConfigurando(true)}>
            <Icono nombre="settings" tam={19} /> Configuración
          </button>
        </Can>
        <Can permiso="ORDENES_COMPRA.CREAR">
          <button type="button" className="primario boton-cabecera" onClick={() => navegar('/compras/ordenes/nueva')}>
            <Icono nombre="agregar" tam={20} /> Nueva orden
          </button>
        </Can>
      </CabeceraListado>

      {filtrosAbiertos && (
        <div className="filtros-panel" role="search">
          <label>
            Estado
            <select value={filtros.estado} onChange={filtrar('estado')}>
              <option value="">Todos</option>
              {Object.entries(ESTADOS_ORDEN).map(([valor, e]) => (
                <option key={valor} value={valor}>
                  {e.texto}
                </option>
              ))}
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
          <label>
            <input type="checkbox" checked={Boolean(filtros.pendientes)} onChange={marcar('pendientes')} /> Solo las que aún esperan mercadería
          </label>
          <label>
            <input type="checkbox" checked={Boolean(filtros.atrasadas)} onChange={marcar('atrasadas')} /> Solo las atrasadas
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
                <th className="centrado">#</th>
                <th>Orden</th>
                <th>Fecha</th>
                <th>Proveedor</th>
                <th>Entrega esperada</th>
                <th>Pago</th>
                <th className="num">Total</th>
                <th>Estado</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={9} icono="checklist" titulo="No hay órdenes con esos filtros" descripcion="Crea la primera con el botón «Nueva orden»." />}
              {filas.map((o, i) => (
                <tr key={o.id} className={o.estado === 'ANULADA' ? 'anulado' : undefined}>
                  <td className="centrado celda-suave">{desde + i}</td>
                  <td>
                    <strong>{o.codigo}</strong>
                  </td>
                  <td>{fechaCorta(o.fecha_emision)}</td>
                  <td className="col-texto">{o.proveedor_nombre}</td>
                  <td>
                    {o.fecha_entrega ? fechaCorta(o.fecha_entrega) : <span className="celda-suave">—</span>}
                    {o.atrasada && (
                      <span className="pildora" data-tono="rojo">
                        Atrasada
                      </span>
                    )}
                  </td>
                  <td className="celda-suave">{o.forma_pago === 'CREDITO' ? `${FORMAS_PAGO.CREDITO} ${o.plazo_dias} d` : FORMAS_PAGO.CONTADO}</td>
                  <td className="num">{dinero(o.total, o.moneda)}</td>
                  <td>
                    <span className="pildora" data-tono={ESTADOS_ORDEN[o.estado].tono}>
                      {ESTADOS_ORDEN[o.estado].texto}
                    </span>
                  </td>
                  <td className="centrado">
                    <span className="acciones-fila">
                      <button type="button" className="accion-icono ver" aria-label={`Ver la orden ${o.codigo}`} title="Ver detalle" onClick={() => navegar(`/compras/ordenes/${o.id}`)}>
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
        onTamano={(t) => {
          setTamano(t)
          setPagina(1)
        }}
      />
      {configurando && <ConfiguracionOrdenesModal empresaId={empresaActivaId} onCerrar={() => setConfigurando(false)} />}
    </main>
  )
}
