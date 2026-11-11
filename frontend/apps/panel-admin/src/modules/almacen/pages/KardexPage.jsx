import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../../../core/api/client'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useListado } from '../../../shared/hooks/useListado'
import MovimientoDetalleModal from '../components/MovimientoDetalleModal'
import SelectorProducto from '../components/SelectorProducto'
import { useOpciones } from '../hooks/useOpciones'
import { cantidad, fechaCorta, ORIGENES, solesUnitario, TIPOS_MOVIMIENTO } from '../inventario'
import { soles } from '../utilidades'
import '../inventario.css'

/** Historial de un producto en un almacén: cada movimiento con el saldo y el costo promedio que dejó. */
export default function KardexPage() {
  const { empresaActivaId } = useEmpresas()
  const [params] = useSearchParams()
  const productoInicial = params.get('producto')
  const [almacen, setAlmacen] = useState(params.get('almacen') ?? '')
  const [producto, setProducto] = useState(productoInicial && /^\d+$/.test(productoInicial) ? { id: Number(productoInicial) } : null)
  const [rango, setRango] = useState({ desde: '', hasta: '' })
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [verMovimiento, setVerMovimiento] = useState(null)

  const almacenes = useOpciones('/mantenimiento/almacenes/', { empresa: empresaActivaId }, { enabled: Boolean(empresaActivaId) })
  const almacenElegido = almacen || String(almacenes.data?.[0]?.id ?? '')

  // Si se llegó desde el Stock solo se conoce el id del producto: se pide su nombre.
  const ficha = useQuery({
    queryKey: ['productos', 'ficha-corta', producto?.id],
    queryFn: ({ signal }) => api.get(`/mantenimiento/productos/${producto.id}/`, { signal }).then((r) => r.data),
    enabled: Boolean(producto?.id) && !producto?.nombre,
    staleTime: 60_000,
  })
  const productoMostrado = producto && { ...producto, nombre: producto.nombre ?? ficha.data?.nombre ?? 'Cargando…', codigo: producto.codigo ?? ficha.data?.codigo }

  const listo = Boolean(empresaActivaId && almacenElegido && producto?.id)
  const consulta = useListado(
    ['kardex'],
    '/inventario/kardex/',
    { empresa: empresaActivaId, almacen: almacenElegido, producto: producto?.id, ...rango, page: pagina, page_size: tamano },
    { enabled: listo },
  )
  const filas = consulta.data?.results ?? []
  const inicio = consulta.data?.saldo_inicial
  // Sin producto elegido se ofrecen los últimos que tuvieron movimiento en el almacén.
  const recientes = useListado(
    ['stock', 'recientes'],
    '/inventario/stock/',
    { empresa: empresaActivaId, almacen: almacenElegido, orden: 'reciente', incluir_cero: '1', page: 1, page_size: 8 },
    { enabled: Boolean(empresaActivaId && almacenElegido && !producto) },
  )
  const sugeridos = recientes.data?.results ?? []
  const rangoInvalido = rango.desde && rango.hasta && rango.desde > rango.hasta

  const cambiarRango = (campo) => (e) => {
    setRango((previo) => ({ ...previo, [campo]: e.target.value }))
    setPagina(1)
  }

  return (
    <main className="listado">
      <CabeceraListado icono="history" titulo="Kardex" descripcion="Historial de un producto en un almacén, con el saldo después de cada movimiento (inventario permanente valorizado)." />

      <div className="filtros-panel" role="search">
        <div style={{ minWidth: 280, flex: '1 1 280px' }}>
          <SelectorProducto
            valor={productoMostrado}
            onElegir={(p) => {
              setProducto(p)
              setPagina(1)
            }}
          />
        </div>
        <label>
          Almacén
          <select value={almacenElegido} onChange={(e) => { setAlmacen(e.target.value); setPagina(1) }}>
            {(almacenes.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>{a.nombre}</option>
            ))}
          </select>
        </label>
        <label>
          Desde
          <input type="date" value={rango.desde} onChange={cambiarRango('desde')} />
        </label>
        <label>
          Hasta
          <input type="date" value={rango.hasta} onChange={cambiarRango('hasta')} />
        </label>
        {rangoInvalido && <p role="alert" className="campo-error">«Desde» no puede ser posterior a «Hasta».</p>}
      </div>

      {!listo ? (
        <section className="kardex-inicio" aria-label="Cómo empezar">
          <h3>Elige un producto para ver su Kardex</h3>
          <p>
            Escribe su nombre o código en el buscador de arriba, o entra desde <Link to="/almacen/stock">Stock</Link> con el icono del reloj de cada fila. Para todos los productos a la vez, usa <Link to="/almacen/reportes">Reportes</Link>.
          </p>
          {recientes.isLoading && <p className="celda-suave">Buscando los últimos movimientos…</p>}
          {recientes.isError && <p role="alert" className="campo-error">No se pudieron cargar los últimos movimientos.</p>}
          {recientes.isSuccess && sugeridos.length === 0 && (
            <p className="celda-suave">Este almacén aún no tiene movimientos. Registra una entrada en <Link to="/almacen/movimientos">Movimientos</Link> y aparecerá aquí.</p>
          )}
          {sugeridos.length > 0 && (
            <>
              <h4>Con movimiento reciente</h4>
              <ul className="kardex-recientes">
                {sugeridos.map((s) => (
                  <li key={s.id}>
                    <button type="button" onClick={() => { setProducto({ id: s.producto, nombre: s.producto_nombre, codigo: s.producto_codigo }); setPagina(1) }}>
                      <strong>{s.producto_nombre}</strong>
                      <span className="sub-texto">{s.producto_codigo} · Stock {cantidad(s.cantidad)} {s.unidad}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      ) : (
        <>
          <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
            <div className="marco-tabla">
              <table className="tabla-datos">
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>N°</th>
                    <th>Movimiento</th>
                    <th>Comprobante</th>
                    <th className="num">Entrada</th>
                    <th className="num">Salida</th>
                    <th className="num">Costo unitario</th>
                    <th className="num">Costo total</th>
                    <th className="num">Saldo</th>
                    <th className="num">Costo promedio</th>
                    <th className="num">Saldo valorizado</th>
                  </tr>
                </thead>
                <tbody>
                  {rango.desde && pagina === 1 && inicio && (
                    <tr className="fila-saldo">
                      <td colSpan={8}>Saldo inicial al {fechaCorta(rango.desde)}</td>
                      <td className="num">{cantidad(inicio.cantidad)}</td>
                      <td className="num">{solesUnitario(inicio.costo_unitario)}</td>
                      <td className="num">{soles(inicio.costo_total)}</td>
                    </tr>
                  )}
                  {filas.length === 0 && (
                    <FilaVacia columnas={11} icono="history" titulo="No hay movimientos de este producto" descripcion="Cuando se registre una compra, un ajuste o una venta, aparecerá aquí." />
                  )}
                  {filas.map((l) => (
                    <tr key={l.id} className={l.estado_movimiento === 'ANULADO' ? 'anulado' : undefined}>
                        <td>{fechaCorta(l.fecha)}</td>
                        <td>
                          <button type="button" className="enlace-boton" onClick={() => setVerMovimiento(l.movimiento)}>
                            {String(l.movimiento_numero).padStart(6, '0')}
                          </button>
                        </td>
                        <td>
                          <span className="pildora" data-tono={TIPOS_MOVIMIENTO[l.tipo].tono}>{TIPOS_MOVIMIENTO[l.tipo].texto}</span>
                          <span className="sub-texto">{ORIGENES[l.origen]}{l.estado_movimiento === 'ANULADO' ? ' · anulado' : ''}</span>
                        </td>
                        <td className="col-texto">{l.comprobante_numero ? `${l.comprobante_serie ? `${l.comprobante_serie}-` : ''}${l.comprobante_numero}` : '—'}</td>
                        <td className="num">{l.tipo === 'ENTRADA' ? cantidad(l.cantidad) : ''}</td>
                        <td className="num">{l.tipo === 'SALIDA' ? cantidad(l.cantidad) : ''}</td>
                        <td className="num">{solesUnitario(l.costo_unitario)}</td>
                        <td className="num">{soles(l.costo_total)}</td>
                        <td className="num">{cantidad(l.saldo_cantidad)}</td>
                        <td className="num">{solesUnitario(l.saldo_costo_unitario)}</td>
                        <td className="num">{soles(l.saldo_costo_total)}</td>
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
        </>
      )}
      {verMovimiento && <MovimientoDetalleModal id={verMovimiento} onCerrar={() => setVerMovimiento(null)} />}
    </main>
  )
}
