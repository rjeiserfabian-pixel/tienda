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
import ImpresionProforma from '../components/ImpresionProforma'
import { ESTADOS_PROFORMA } from '../ventas'
import '../../almacen/inventario.css'
import '../ventas.css'

const RUTA = '/ventas/proformas'

/** Proformas: las cotizaciones del mostrador, con su estado (vigente, vencida, vendida o anulada). */
export default function ProformasPage() {
  const navegar = useNavigate()
  const { empresaActivaId } = useEmpresas()
  const [busqueda, setBusqueda] = useState('')
  const [estado, setEstado] = useState('')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [impresion, setImpresion] = useState(null) // { id, vez }: cada clic en Imprimir vuelve a montarla
  const q = useDebounce(busqueda, 400)
  const consulta = useListado(['ventas', 'proformas'], '/ventas/proformas/', { empresa: empresaActivaId, q, estado, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []

  return (
    <main className="listado">
      <CabeceraListado icono="cotizacion" titulo="Proformas" descripcion="Cotizaciones que no mueven stock ni dinero. Cuando el cliente acepta, se convierten en venta con un clic: ahí se descuenta el stock y se cobra en caja.">
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar proformas"
          placeholder="Cliente, documento, número…"
        />
        <select aria-label="Estado" value={estado} onChange={(e) => { setEstado(e.target.value); setPagina(1) }}>
          <option value="">Todas</option>
          <option value="vigente">Vigentes</option>
          <option value="vencida">Vencidas</option>
          <option value="vendida">Vendidas</option>
          <option value="anulada">Anuladas</option>
        </select>
        <Can permiso="VENTAS.VENDER">
          <button type="button" className="primario boton-cabecera" onClick={() => navegar(`${RUTA}/nueva`)}>
            <Icono nombre="agregar" tam={20} /> Nueva proforma
          </button>
        </Can>
      </CabeceraListado>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Fecha</th>
                <th>N°</th>
                <th>Cliente</th>
                <th>Vendedor</th>
                <th>Válida hasta</th>
                <th className="num">Total</th>
                <th className="col-ajustada">Estado</th>
                <th className="col-acciones">
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={8} icono="cotizacion" titulo="No hay proformas con esos filtros" descripcion="Crea una con «Nueva proforma»." />}
              {filas.map((p) => {
                const e = ESTADOS_PROFORMA[p.estado_proforma]
                return (
                  <tr key={p.id} className={`fila-clicable${p.estado === 'ANULADO' ? ' anulado' : ''}`} onClick={() => navegar(`${RUTA}/${p.id}`)}>
                    <td>{fechaCorta(p.fecha)}</td>
                    <td className="celda-suave">{p.numero_completo}</td>
                    <td className="col-texto">
                      {p.cliente_nombre}
                      {p.cliente_documento && <span className="sub-texto">{p.cliente_documento}</span>}
                    </td>
                    <td className="celda-suave">{p.vendedor_nombre}</td>
                    <td>{fechaCorta(p.valida_hasta)}</td>
                    <td className="num">{dinero(p.total, p.moneda)}</td>
                    <td className="col-ajustada">
                      <span className="pildora" data-tono={e.tono}>
                        {e.texto}
                      </span>
                    </td>
                    <td className="col-acciones">
                      {(p.estado_proforma === 'VIGENTE' || p.estado_proforma === 'VENCIDA') && (
                        <Can permiso="VENTAS.VENDER">
                          <button
                            type="button"
                            className="accion-icono"
                            aria-label={`Convertir la proforma ${p.numero} en venta`}
                            title="Convertir en venta"
                            onClick={(ev) => {
                              ev.stopPropagation()
                              navegar(`/ventas/pos?proforma=${p.id}`)
                            }}
                          >
                            <Icono nombre="cart" tam={19} />
                          </button>
                        </Can>
                      )}{' '}
                      <button
                        type="button"
                        className="accion-icono"
                        aria-label={`Imprimir la proforma ${p.numero_completo}`}
                        title="Imprimir"
                        onClick={(ev) => {
                          ev.stopPropagation()
                          setImpresion((previa) => ({ id: p.id, vez: (previa?.vez ?? 0) + 1 }))
                        }}
                      >
                        <Icono nombre="documento" tam={19} />
                      </button>{' '}
                      <button
                        type="button"
                        className="accion-icono"
                        aria-label={`Abrir la proforma ${p.numero}`}
                        title="Ver"
                        onClick={(ev) => {
                          ev.stopPropagation()
                          navegar(`${RUTA}/${p.id}`)
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
      {impresion && <ImpresionProforma key={impresion.vez} id={impresion.id} />}
    </main>
  )
}
