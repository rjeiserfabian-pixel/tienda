import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
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
import AnularMovimientoModal from '../components/AnularMovimientoModal'
import CierreMensualModal from '../components/CierreMensualModal'
import MovimientoDetalleModal from '../components/MovimientoDetalleModal'
import MovimientoFormModal from '../components/MovimientoFormModal'
import TraspasoModal from '../components/TraspasoModal'
import { useOpciones } from '../hooks/useOpciones'
import { fechaCorta, ORIGENES, TIPOS_MOVIMIENTO } from '../inventario'
import '../inventario.css'

const FILTROS_VACIOS = { tipo: '', origen: '', estado: '', almacen: '', desde: '', hasta: '' }

/** Entradas y salidas de la empresa activa: se registran, se consultan y se anulan (con extorno). */
export default function MovimientosPage() {
  const { empresaActivaId } = useEmpresas()
  const { tiene } = usePermisos()
  const puedeAnular = tiene('INVENTARIO.MOVIMIENTOS.ANULAR')
  const puedeGuia = tiene('VENTAS.GUIA_REMISION')
  const navegar = useNavigate()
  const [busqueda, setBusqueda] = useState('')
  const [filtros, setFiltros] = useState(FILTROS_VACIOS)
  const [filtrosAbiertos, setFiltrosAbiertos] = useState(false)
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [dialogo, setDialogo] = useState(null) // { tipo: 'nuevo' | 'traspaso' | 'cierre' | 'ver' | 'anular', movimiento? }
  const q = useDebounce(busqueda, 400)

  const almacenes = useOpciones('/mantenimiento/almacenes/', { empresa: empresaActivaId }, { enabled: Boolean(empresaActivaId) })
  const consulta = useListado(['movimientos'], '/inventario/movimientos/', { empresa: empresaActivaId, q, ...filtros, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
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
      <CabeceraListado icono="tabla" titulo="Movimientos" descripcion="Entradas y salidas de mercadería. Cada movimiento actualiza el stock y el costo promedio.">
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar movimientos"
          placeholder="Comprobante, proveedor, cliente…"
        />
        <button type="button" className={`boton-cabecera${filtrosAbiertos || hayFiltros ? ' activo' : ''}`} aria-expanded={filtrosAbiertos} onClick={() => setFiltrosAbiertos((v) => !v)}>
          <Icono nombre="filtro" tam={19} /> Filtros{hayFiltros ? ' •' : ''}
        </button>
        <Can permiso="INVENTARIO.PERIODOS.CERRAR">
          <button type="button" className="boton-cabecera" onClick={() => setDialogo({ tipo: 'cierre' })}>
            <Icono nombre="calendario" tam={19} /> Cierre mensual
          </button>
        </Can>
        <Can permiso="INVENTARIO.TRASPASOS.REGISTRAR">
          <button type="button" className="boton-cabecera" onClick={() => setDialogo({ tipo: 'traspaso' })}>
            <Icono nombre="swap" tam={19} /> Traspasar
          </button>
        </Can>
        <Can permiso="INVENTARIO.MOVIMIENTOS.REGISTRAR">
          <button type="button" className="primario boton-cabecera" onClick={() => setDialogo({ tipo: 'nuevo' })}>
            <Icono nombre="agregar" tam={20} /> Registrar movimiento
          </button>
        </Can>
      </CabeceraListado>

      {filtrosAbiertos && (
        <div className="filtros-panel" role="search">
          <label>
            Movimiento
            <select value={filtros.tipo} onChange={filtrar('tipo')}>
              <option value="">Entradas y salidas</option>
              {Object.entries(TIPOS_MOVIMIENTO).map(([v, { texto }]) => (
                <option key={v} value={v}>{texto}s</option>
              ))}
            </select>
          </label>
          <label>
            Motivo
            <select value={filtros.origen} onChange={filtrar('origen')}>
              <option value="">Todos</option>
              {Object.entries(ORIGENES).map(([v, t]) => (
                <option key={v} value={v}>{t}</option>
              ))}
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
          {(almacenes.data ?? []).length > 1 && (
            <label>
              Almacén
              <select value={filtros.almacen} onChange={filtrar('almacen')}>
                <option value="">Todos</option>
                {almacenes.data.map((a) => (
                  <option key={a.id} value={a.id}>{a.nombre}</option>
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
            <button type="button" onClick={() => { setFiltros(FILTROS_VACIOS); setPagina(1) }}>
              Limpiar filtros
            </button>
          )}
          {rangoInvalido && <p role="alert" className="campo-error">«Desde» no puede ser posterior a «Hasta».</p>}
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
                <th>Movimiento</th>
                <th>Comprobante</th>
                <th>Proveedor / cliente</th>
                <th>Almacén</th>
                <th className="num">Total</th>
                <th>Estado</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && (
                <FilaVacia columnas={10} icono="tabla" titulo="No hay movimientos con esos filtros" descripcion="Registra una compra o un saldo inicial con el botón «Registrar movimiento»." />
              )}
              {filas.map((m, i) => (
                <tr key={m.id} className={m.estado === 'ANULADO' ? 'anulado' : undefined}>
                  <td className="centrado celda-suave">{desde + i}</td>
                  <td className="celda-suave">{String(m.numero).padStart(6, '0')}</td>
                  <td>{fechaCorta(m.fecha)}</td>
                  <td>
                    <span className="pildora" data-tono={TIPOS_MOVIMIENTO[m.tipo].tono}>{TIPOS_MOVIMIENTO[m.tipo].texto}</span>
                    <span className="sub-texto">{ORIGENES[m.origen]}</span>
                  </td>
                  <td className="col-texto">{m.comprobante_numero ? `${m.comprobante_serie ? `${m.comprobante_serie}-` : ''}${m.comprobante_numero}` : '—'}</td>
                  <td className="col-texto celda-suave">{m.tercero || '—'}</td>
                  <td>{m.almacen_nombre}</td>
                  <td className="num">{Number(m.total) > 0 ? `${m.moneda === 'USD' ? 'US$' : 'S/'} ${m.total}` : '—'}</td>
                  <td>
                    {m.estado === 'ANULADO' ? <span className="estado-pildora inactivo">Anulado</span> : <span className="estado-pildora activo">Vigente</span>}
                  </td>
                  <td className="centrado">
                    <span className="acciones-fila">
                      <button type="button" className="accion-icono ver" aria-label={`Ver el movimiento ${m.numero}`} title="Ver detalle" onClick={() => setDialogo({ tipo: 'ver', movimiento: m })}>
                        <Icono nombre="ojo" tam={19} />
                      </button>
                      {puedeGuia && m.traspaso_id && m.origen === 'TRASPASO' && m.estado === 'EMITIDO' && (
                        <button type="button" className="accion-icono" aria-label={`Crear la guía de remisión del traspaso ${m.numero}`} title="Crear guía de remisión" onClick={() => navegar(`/ventas/guias-remision/nueva?traspaso=${m.id}`)}>
                          <Icono nombre="truck" tam={19} />
                        </button>
                      )}
                      {puedeAnular && m.estado === 'EMITIDO' && m.origen !== 'EXTORNO' && (
                        <button type="button" className="accion-icono peligro-suave" aria-label={`Anular el movimiento ${m.numero}`} title="Anular" onClick={() => setDialogo({ tipo: 'anular', movimiento: m })}>
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
      <p className="celda-suave">
        ¿Quieres ver el historial de un producto con su saldo? Abre el <Link to="/almacen/kardex">Kardex</Link>.
      </p>

      {dialogo?.tipo === 'nuevo' && <MovimientoFormModal onCerrar={cerrar} />}
      {dialogo?.tipo === 'traspaso' && <TraspasoModal onCerrar={cerrar} />}
      {dialogo?.tipo === 'cierre' && <CierreMensualModal onCerrar={cerrar} />}
      {dialogo?.tipo === 'ver' && <MovimientoDetalleModal id={dialogo.movimiento.id} onCerrar={cerrar} />}
      {dialogo?.tipo === 'anular' && <AnularMovimientoModal movimiento={dialogo.movimiento} onCerrar={cerrar} />}
    </main>
  )
}
