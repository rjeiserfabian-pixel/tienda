import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
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
import { dinero } from '../../compras/compras'
import ReimprimirModal from '../components/ReimprimirModal'
import { ESTADOS_VENTA, FORMAS_PAGO, numeroInterno } from '../ventas'
import '../../almacen/inventario.css'
import '../ventas.css'

const RUTA = '/ventas/historial'
const FILTROS_VACIOS = { estado: '', forma_pago: '', vendedor: '', desde: '', hasta: '' }

/** Historial de ventas del mostrador: cada venta con sus comprobantes (uno por empresa). */
export default function VentasPage() {
  const navegar = useNavigate()
  const { empresaActivaId } = useEmpresas()
  const [busqueda, setBusqueda] = useState('')
  const [filtros, setFiltros] = useState(FILTROS_VACIOS)
  const [filtrosAbiertos, setFiltrosAbiertos] = useState(false)
  const [pagina, setPagina] = useState(1)
  const [reimprimiendo, setReimprimiendo] = useState(null)
  const [tamano, setTamano] = useState(25)
  const q = useDebounce(busqueda, 400)

  const consulta = useListado(['ventas', 'lista'], '/ventas/', { empresa: empresaActivaId, q, ...filtros, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []
  const hayFiltros = Object.values(filtros).some(Boolean)
  const rangoInvalido = filtros.desde && filtros.hasta && filtros.desde > filtros.hasta
  const filtrar = (campo) => (e) => {
    setFiltros((previos) => ({ ...previos, [campo]: e.target.value }))
    setPagina(1)
  }

  return (
    <main className="listado">
      <CabeceraListado icono="cart" titulo="Historial de ventas" descripcion="Todas las ventas del mostrador, con los comprobantes que emitió cada empresa.">
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar ventas"
          placeholder="Cliente, documento, número…"
        />
        <button type="button" className={`boton-cabecera${filtrosAbiertos || hayFiltros ? ' activo' : ''}`} aria-expanded={filtrosAbiertos} onClick={() => setFiltrosAbiertos((v) => !v)}>
          <Icono nombre="filtro" tam={19} /> Filtros{hayFiltros ? ' •' : ''}
        </button>
        <Can permiso="VENTAS.VENDER">
          <button type="button" className="primario boton-cabecera" onClick={() => navegar('/ventas/pos')}>
            <Icono nombre="agregar" tam={20} /> Nueva venta
          </button>
        </Can>
      </CabeceraListado>

      {filtrosAbiertos && (
        <div className="filtros-panel" role="search">
          <label>
            Estado
            <select value={filtros.estado} onChange={filtrar('estado')}>
              <option value="">Todas</option>
              <option value="EMITIDO">Vigentes</option>
              <option value="ANULADO">Anuladas</option>
            </select>
          </label>
          <label>
            Forma de pago
            <select value={filtros.forma_pago} onChange={filtrar('forma_pago')}>
              <option value="">Todas</option>
              <option value="CONTADO">Al contado</option>
              <option value="CREDITO">A crédito</option>
            </select>
          </label>
          <label>
            Vendedor
            <input type="search" placeholder="Nombre" value={filtros.vendedor} onChange={filtrar('vendedor')} />
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
                <th>Cliente</th>
                <th>Comprobantes</th>
                <th>Vendedor</th>
                <th className="num">Total</th>
                <th>Pago</th>
                <th>Estado</th>
                <th className="centrado">
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={9} icono="cart" titulo="No hay ventas con esos filtros" descripcion="Registra una venta desde el punto de venta." />}
              {filas.map((v) => {
                const estado = ESTADOS_VENTA[v.estado]
                return (
                  <tr key={v.id} className={`fila-clicable${v.estado === 'ANULADO' ? ' anulado' : ''}`} onClick={() => navegar(`${RUTA}/${v.id}`)}>
                    <td>{fechaCorta(v.fecha)}</td>
                    <td className="celda-suave">
                      {numeroInterno(v)}
                      {v.mostrador !== empresaActivaId && <span className="sub-texto">Vendida en {v.mostrador_nombre}</span>}
                    </td>
                    <td className="col-texto">
                      {v.cliente_nombre}
                      {v.cliente_documento && (
                        <span className="sub-texto">
                          {v.cliente_tipo_documento} {v.cliente_documento}
                        </span>
                      )}
                    </td>
                    <td>
                      {v.comprobantes.map((c) => (
                        <span key={c.id} className={`sub-texto venta-comprobante${c.empresa === empresaActivaId && v.comprobantes.length > 1 ? ' propio' : ''}`} data-anulado={c.estado === 'ANULADO' || undefined}>
                          {c.numero_completo} · {c.empresa_nombre}
                        </span>
                      ))}
                    </td>
                    <td className="celda-suave">{v.vendedor_nombre}</td>
                    <td className="num">
                      {dinero(v.total, v.moneda)}
                      {v.parcial && <span className="sub-texto">Tu parte</span>}
                    </td>
                    <td>
                      <span className="pildora" data-tono={v.forma_pago === 'CREDITO' ? 'ambar' : 'gris'}>
                        {FORMAS_PAGO[v.forma_pago]}
                      </span>
                    </td>
                    <td>
                      <span className="pildora" data-tono={estado.tono}>
                        {estado.texto}
                      </span>
                    </td>
                    <td className="centrado">
                      <button
                        type="button"
                        className="accion-icono"
                        aria-label={`Reimprimir los comprobantes de la venta ${numeroInterno(v)}`}
                        title="Reimprimir"
                        onClick={(ev) => {
                          ev.stopPropagation()
                          setReimprimiendo(v.id)
                        }}
                      >
                        <Icono nombre="documento" tam={19} />
                      </button>{' '}
                      <button
                        type="button"
                        className="accion-icono"
                        aria-label={`Abrir la venta ${v.numero}`}
                        title="Ver"
                        onClick={(ev) => {
                          ev.stopPropagation()
                          navegar(`${RUTA}/${v.id}`)
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
      {reimprimiendo && <ReimprimirModal ventaId={reimprimiendo} onCerrar={() => setReimprimiendo(null)} />}

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
