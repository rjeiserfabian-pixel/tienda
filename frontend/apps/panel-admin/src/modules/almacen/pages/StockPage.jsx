import { useState } from 'react'
import { Link } from 'react-router-dom'
import Can from '../../../shared/components/Can'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import ImportarSaldoInicialModal from '../components/ImportarSaldoInicialModal'
import { useOpciones } from '../hooks/useOpciones'
import { cantidad, solesUnitario } from '../inventario'
import { soles } from '../utilidades'
import '../inventario.css'

/** Existencias de la empresa activa por almacén, con su costo promedio y alerta de stock bajo. */
export default function StockPage() {
  const { empresaActivaId, empresaActiva } = useEmpresas()
  const [busqueda, setBusqueda] = useState('')
  const [almacen, setAlmacen] = useState('')
  const [soloBajos, setSoloBajos] = useState(false)
  const [conCero, setConCero] = useState(false)
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [importando, setImportando] = useState(false)
  const q = useDebounce(busqueda, 400)

  const almacenes = useOpciones('/mantenimiento/almacenes/', { empresa: empresaActivaId }, { enabled: Boolean(empresaActivaId) })
  const consulta = useListado(
    ['stock'],
    '/inventario/stock/',
    {
      empresa: empresaActivaId,
      q,
      almacen,
      bajo_minimo: soloBajos ? '1' : '',
      incluir_cero: conCero ? '1' : '',
      page: pagina,
      page_size: tamano,
    },
    { enabled: Boolean(empresaActivaId) },
  )
  const filas = consulta.data?.results ?? []
  const desde = (pagina - 1) * tamano + 1

  const cambiar = (poner) => (valor) => {
    poner(valor)
    setPagina(1)
  }

  return (
    <main className="listado">
      <CabeceraListado
        icono="box"
        titulo="Stock"
        descripcion={`Existencias de ${empresaActiva?.nombre_comercial || empresaActiva?.razon_social || 'la empresa'} por almacén. Cada empresa lleva su propio stock y su propio costo.`}
      >
        <Buscador valor={busqueda} onCambio={cambiar(setBusqueda)} etiqueta="Buscar en el stock" placeholder="Buscar producto o código…" />
        {(almacenes.data ?? []).length > 1 && (
          <select className="boton-cabecera" aria-label="Almacén" value={almacen} onChange={(e) => cambiar(setAlmacen)(e.target.value)}>
            <option value="">Todos los almacenes</option>
            {almacenes.data.map((a) => (
              <option key={a.id} value={a.id}>{a.nombre}</option>
            ))}
          </select>
        )}
        <button type="button" className={`boton-cabecera${soloBajos ? ' activo' : ''}`} aria-pressed={soloBajos} onClick={() => cambiar(setSoloBajos)(!soloBajos)}>
          <Icono nombre="bell" tam={19} /> Stock bajo
        </button>
        <button type="button" className={`boton-cabecera${conCero ? ' activo' : ''}`} aria-pressed={conCero} onClick={() => cambiar(setConCero)(!conCero)}>
          Incluir sin stock
        </button>
        <Can permiso="INVENTARIO.SALDO_INICIAL.CARGAR">
          <button type="button" className="primario boton-cabecera" onClick={() => setImportando(true)}>
            <Icono nombre="importar" tam={19} /> Importar saldo inicial
          </button>
        </Can>
      </CabeceraListado>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th className="centrado">#</th>
                <th>Código</th>
                <th>Producto</th>
                <th>Almacén</th>
                <th>Ubicación</th>
                <th className="num">Stock</th>
                <th className="num">Costo promedio</th>
                <th className="num">Valor</th>
                <th>Estado</th>
                <th className="centrado">Kardex</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && (
                <FilaVacia columnas={10} icono="box" titulo="No hay existencias con esos filtros" descripcion="Cuando registres compras o un saldo inicial, el stock aparecerá aquí." />
              )}
              {filas.map((s, i) => (
                <tr key={s.id}>
                  <td className="centrado celda-suave">{desde + i}</td>
                  <td className="celda-suave">{s.producto_codigo}</td>
                  <td>
                    <strong>{s.producto_nombre}</strong>
                  </td>
                  <td>{s.almacen_nombre}</td>
                  <td>
                    {s.ubicacion_codigo ? (
                      <span className="pildora" data-tono="azul" title={s.ubicacion_nombre}>
                        {s.ubicacion_codigo}
                      </span>
                    ) : (
                      <span className="celda-suave">—</span>
                    )}
                  </td>
                  <td className="num">
                    {cantidad(s.cantidad)} {s.unidad}
                    {Number(s.stock_minimo) > 0 && <span className="sub-texto">Mínimo {cantidad(s.stock_minimo)}</span>}
                  </td>
                  <td className="num">{solesUnitario(s.costo_unitario)}</td>
                  <td className="num">{soles(s.costo_total)}</td>
                  <td>
                    {s.bajo_minimo ? <span className="pildora" data-tono="ambar">Stock bajo</span> : Number(s.cantidad) === 0 ? <span className="pildora" data-tono="gris">Sin stock</span> : <span className="estado-pildora activo">Normal</span>}
                  </td>
                  <td className="centrado">
                    <Link to={`/almacen/kardex?almacen=${s.almacen}&producto=${s.producto}`} className="accion-icono ver" aria-label={`Ver el Kardex de ${s.producto_nombre}`} title="Ver Kardex">
                      <Icono nombre="history" tam={19} />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </EstadoConsulta>

      <Paginacion pagina={pagina} tamano={tamano} total={consulta.data?.count ?? 0} onPagina={setPagina} onTamano={(t) => cambiar(setTamano)(t)} />
      {importando && <ImportarSaldoInicialModal onCerrar={() => setImportando(false)} />}
    </main>
  )
}
