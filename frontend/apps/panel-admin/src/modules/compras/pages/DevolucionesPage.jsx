import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import { fechaCorta } from '../../almacen/inventario'
import { dinero, numeroInterno } from '../compras'
import { destinoDelDinero, ESTADO_DEVOLUCION, MOTIVOS } from '../devoluciones'
import '../../almacen/inventario.css'

const FILTROS_VACIOS = { estado: '', desde: '', hasta: '' }

/** Devoluciones de mercadería a proveedores de la empresa activa. Se registran desde la ficha de la compra. */
export default function DevolucionesPage() {
  const navegar = useNavigate()
  const { empresaActivaId } = useEmpresas()
  const [busqueda, setBusqueda] = useState('')
  const [filtros, setFiltros] = useState(FILTROS_VACIOS)
  const [filtrosAbiertos, setFiltrosAbiertos] = useState(false)
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const q = useDebounce(busqueda, 400)

  const consulta = useListado(['compras', 'devoluciones'], '/compras/devoluciones/', { empresa: empresaActivaId, q, ...filtros, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
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
      <CabeceraListado icono="swap" titulo="Devoluciones a proveedores" descripcion="Mercadería que devolviste a tus proveedores, con la nota de crédito que te entregaron. Se registran desde la ficha de cada compra.">
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar devoluciones"
          placeholder="Nota de crédito, proveedor, motivo…"
        />
        <button type="button" className={`boton-cabecera${filtrosAbiertos || hayFiltros ? ' activo' : ''}`} aria-expanded={filtrosAbiertos} onClick={() => setFiltrosAbiertos((v) => !v)}>
          <Icono nombre="filtro" tam={19} /> Filtros{hayFiltros ? ' •' : ''}
        </button>
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
                <th>Nota de crédito</th>
                <th>Compra</th>
                <th>Proveedor</th>
                <th>Tipo</th>
                <th className="num">Total</th>
                <th>Dinero</th>
                <th>Estado</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={11} icono="swap" titulo="No hay devoluciones con esos filtros" descripcion="Para devolver mercadería, abre la compra y usa «Devolver mercadería»." />}
              {filas.map((d, i) => (
                <tr key={d.id} className={d.estado === 'ANULADO' ? 'anulado' : undefined}>
                  <td className="centrado celda-suave">{desde + i}</td>
                  <td className="celda-suave">{numeroInterno(d)}</td>
                  <td>{fechaCorta(d.fecha_emision)}</td>
                  <td className="col-texto">{d.comprobante}</td>
                  <td className="col-texto">
                    N° {numeroInterno({ numero: d.compra_numero })}
                    <span className="sub-texto">{d.compra_comprobante}</span>
                  </td>
                  <td className="col-texto">{d.proveedor_nombre}</td>
                  <td className="celda-suave">{MOTIVOS[d.motivo]}</td>
                  <td className="num">{dinero(d.total, d.moneda)}</td>
                  <td className="celda-suave">{destinoDelDinero(d)}</td>
                  <td>
                    <span className={`estado-pildora ${ESTADO_DEVOLUCION[d.estado].clase}`}>{ESTADO_DEVOLUCION[d.estado].texto}</span>
                  </td>
                  <td className="centrado">
                    <span className="acciones-fila">
                      <button type="button" className="accion-icono ver" aria-label={`Ver la devolución ${d.comprobante}`} title="Ver detalle" onClick={() => navegar(`/compras/devoluciones/${d.id}`)}>
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
