import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
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
import { useOpciones } from '../../almacen/hooks/useOpciones'
import { fechaCorta } from '../../almacen/inventario'
import AnularCompraModal from '../components/AnularCompraModal'
import { dinero, FORMAS_PAGO, numeroInterno } from '../compras'
import '../../almacen/inventario.css'

const FILTROS_VACIOS = { estado: '', forma_pago: '', almacen: '', desde: '', hasta: '' }

/** Compras de la empresa activa: se consultan, se abren y (con permiso) se anulan. Se registran en su propia pantalla. */
export default function ComprasPage() {
  const navegar = useNavigate()
  const { empresaActivaId } = useEmpresas()
  const { tiene } = usePermisos()
  const puedeAnular = tiene('COMPRAS.ANULAR')
  const [busqueda, setBusqueda] = useState('')
  const [filtros, setFiltros] = useState(FILTROS_VACIOS)
  const [filtrosAbiertos, setFiltrosAbiertos] = useState(false)
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [dialogo, setDialogo] = useState(null) // { tipo: 'ver' | 'anular', compra }
  const q = useDebounce(busqueda, 400)

  const almacenes = useOpciones('/mantenimiento/almacenes/', { empresa: empresaActivaId }, { enabled: Boolean(empresaActivaId) })
  const consulta = useListado(['compras'], '/compras/', { empresa: empresaActivaId, q, ...filtros, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []
  const desde = (pagina - 1) * tamano + 1
  const hayFiltros = Object.values(filtros).some(Boolean)
  const rangoInvalido = filtros.desde && filtros.hasta && filtros.desde > filtros.hasta

  const filtrar = (campo) => (e) => {
    setFiltros((previos) => ({ ...previos, [campo]: e.target.value }))
    setPagina(1)
  }
  const cerrar = () => setDialogo(null)

  return (
    <main className="listado">
      <CabeceraListado icono="truck" titulo="Compras" descripcion="Facturas y boletas de tus proveedores. Cada compra ingresa la mercadería al inventario con su costo.">
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar compras"
          placeholder="Comprobante, proveedor, guía…"
        />
        <button type="button" className={`boton-cabecera${filtrosAbiertos || hayFiltros ? ' activo' : ''}`} aria-expanded={filtrosAbiertos} onClick={() => setFiltrosAbiertos((v) => !v)}>
          <Icono nombre="filtro" tam={19} /> Filtros{hayFiltros ? ' •' : ''}
        </button>
        <Can permiso="COMPRAS.CREAR">
          <button type="button" className="primario boton-cabecera" onClick={() => navegar('/compras/registro/nueva')}>
            <Icono nombre="agregar" tam={20} /> Registrar compra
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
              {Object.entries(FORMAS_PAGO).map(([v, t]) => (
                <option key={v} value={v}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          {(almacenes.data ?? []).length > 1 && (
            <label>
              Almacén
              <select value={filtros.almacen} onChange={filtrar('almacen')}>
                <option value="">Todos</option>
                {almacenes.data.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.nombre}
                  </option>
                ))}
              </select>
            </label>
          )}
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
                <th>N°</th>
                <th>Fecha</th>
                <th>Comprobante</th>
                <th>Proveedor</th>
                <th>Almacén</th>
                <th>Pago</th>
                <th className="num">Total</th>
                <th>Estado</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={10} icono="truck" titulo="No hay compras con esos filtros" descripcion="Registra la primera con el botón «Registrar compra»." />}
              {filas.map((c, i) => (
                <tr key={c.id} className={c.estado === 'ANULADO' ? 'anulado' : undefined}>
                  <td className="centrado celda-suave">{desde + i}</td>
                  <td className="celda-suave">{numeroInterno(c)}</td>
                  <td>{fechaCorta(c.fecha_emision)}</td>
                  <td className="col-texto">
                    {c.comprobante}
                    <span className="sub-texto">{c.tipo_comprobante_nombre}</span>
                  </td>
                  <td className="col-texto">{c.proveedor_nombre}</td>
                  <td className="celda-suave">{c.almacen_nombre}</td>
                  <td>
                    <span className="pildora" data-tono={c.forma_pago === 'CREDITO' ? 'ambar' : 'verde'}>
                      {FORMAS_PAGO[c.forma_pago]}
                    </span>
                  </td>
                  <td className="num">{dinero(c.total, c.moneda)}</td>
                  <td>{c.estado === 'ANULADO' ? <span className="estado-pildora inactivo">Anulada</span> : <span className="estado-pildora activo">Vigente</span>}</td>
                  <td className="centrado">
                    <span className="acciones-fila">
                      <button type="button" className="accion-icono ver" aria-label={`Ver la compra ${c.comprobante}`} title="Ver detalle" onClick={() => navegar(`/compras/registro/${c.id}`)}>
                        <Icono nombre="ojo" tam={19} />
                      </button>
                      {puedeAnular && c.estado === 'EMITIDO' && (
                        <button type="button" className="accion-icono peligro-suave" aria-label={`Anular la compra ${c.comprobante}`} title="Anular" onClick={() => setDialogo({ tipo: 'anular', compra: c })}>
                          <Icono nombre="apagar" tam={19} />
                        </button>
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

      {dialogo?.tipo === 'anular' && <AnularCompraModal compra={dialogo.compra} onCerrar={cerrar} />}
    </main>
  )
}
