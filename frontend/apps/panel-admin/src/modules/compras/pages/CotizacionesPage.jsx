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
import { ESTADOS_COTIZACION } from '../cotizaciones'
import '../../almacen/inventario.css'

const FILTROS_VACIOS = { estado: '', desde: '', hasta: '' }
const RUTA = '/compras/cotizaciones'

/** Cotizaciones de la empresa activa: precios pedidos a varios proveedores, antes de hacer la orden de compra. */
export default function CotizacionesPage() {
  const navegar = useNavigate()
  const { empresaActivaId } = useEmpresas()
  const [busqueda, setBusqueda] = useState('')
  const [filtros, setFiltros] = useState(FILTROS_VACIOS)
  const [filtrosAbiertos, setFiltrosAbiertos] = useState(false)
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const q = useDebounce(busqueda, 400)

  const consulta = useListado(['compras', 'cotizaciones'], '/compras/cotizaciones/', { empresa: empresaActivaId, q, ...filtros, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []
  const desde = (pagina - 1) * tamano + 1
  const hayFiltros = Object.values(filtros).some(Boolean)
  const rangoInvalido = filtros.desde && filtros.hasta && filtros.desde > filtros.hasta

  const filtrar = (campo) => (e) => {
    setFiltros((previos) => ({ ...previos, [campo]: e.target.value }))
    setPagina(1)
  }

  return (
    <main className="listado">
      <CabeceraListado icono="cotizacion" titulo="Cotizaciones" descripcion="Pide precio a varios proveedores, compáralos y elige a quién comprarle. De la cotización ganadora salen las órdenes de compra.">
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar cotizaciones"
          placeholder="Número u observación…"
        />
        <button type="button" className={`boton-cabecera${filtrosAbiertos || hayFiltros ? ' activo' : ''}`} aria-expanded={filtrosAbiertos} onClick={() => setFiltrosAbiertos((v) => !v)}>
          <Icono nombre="filtro" tam={19} /> Filtros{hayFiltros ? ' •' : ''}
        </button>
        <Can permiso="COTIZACIONES_COMPRA.CREAR">
          <button type="button" className="primario boton-cabecera" onClick={() => navegar(`${RUTA}/nueva`)}>
            <Icono nombre="agregar" tam={20} /> Nueva cotización
          </button>
        </Can>
      </CabeceraListado>

      {filtrosAbiertos && (
        <div className="filtros-panel" role="search">
          <label>
            Estado
            <select value={filtros.estado} onChange={filtrar('estado')}>
              <option value="">Todos</option>
              {Object.entries(ESTADOS_COTIZACION).map(([valor, e]) => (
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
                <th>Cotización</th>
                <th>Fecha</th>
                <th>Responder hasta</th>
                <th>Almacén</th>
                <th className="num">Productos</th>
                <th className="num">Respuestas</th>
                <th>Estado</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={9} icono="cotizacion" titulo="No hay cotizaciones con esos filtros" descripcion="Crea la primera con el botón «Nueva cotización»." />}
              {filas.map((c, i) => (
                <tr key={c.id} className={c.estado === 'ANULADA' ? 'anulado' : undefined}>
                  <td className="centrado celda-suave">{desde + i}</td>
                  <td>
                    <strong>{c.codigo}</strong>
                  </td>
                  <td>{fechaCorta(c.fecha)}</td>
                  <td>{c.fecha_limite ? fechaCorta(c.fecha_limite) : <span className="celda-suave">—</span>}</td>
                  <td className="col-texto">{c.almacen_nombre}</td>
                  <td className="num">{c.lineas}</td>
                  <td className="num">
                    {c.respondidas} de {c.proveedores}
                  </td>
                  <td>
                    <span className="pildora" data-tono={ESTADOS_COTIZACION[c.estado]?.tono ?? 'gris'}>
                      {ESTADOS_COTIZACION[c.estado]?.texto ?? c.estado}
                    </span>
                  </td>
                  <td className="centrado">
                    <span className="acciones-fila">
                      <button type="button" className="accion-icono ver" aria-label={`Ver la cotización ${c.codigo}`} title="Ver detalle" onClick={() => navegar(`${RUTA}/${c.id}`)}>
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
    </main>
  )
}
