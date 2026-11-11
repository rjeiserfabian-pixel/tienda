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
import { sinVacios, useListado } from '../../../shared/hooks/useListado'
import { fechaCorta } from '../../almacen/inventario'
import { BotonDescarga } from '../../caja/components/ReporteComun'
import { dinero } from '../../compras/compras'
import ImpresionNotaCredito from '../components/ImpresionNotaCredito'
import NotaCreditoDetalleModal from '../components/NotaCreditoDetalleModal'
import '../../almacen/inventario.css'
import '../ventas.css'

/**
 * Notas de crédito: las devoluciones a clientes. Cada fila se abre o se imprime desde sus botones;
 * «Reporte» baja a Excel lo que se ve (con los mismos filtros). Una nota no se anula: un error se
 * corrige con otra operación.
 */
export default function NotasCreditoPage() {
  const navegar = useNavigate()
  const { empresaActivaId } = useEmpresas()
  const [busqueda, setBusqueda] = useState('')
  const [desde, setDesde] = useState('')
  const [hasta, setHasta] = useState('')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [abierta, setAbierta] = useState(null)
  const [impresion, setImpresion] = useState(null) // { id, vez }: cada clic en Imprimir vuelve a montarla
  const [errorReporte, setErrorReporte] = useState('')
  const q = useDebounce(busqueda, 400)
  const filtros = { empresa: empresaActivaId, q, desde, hasta }
  const consulta = useListado(['ventas', 'notas-credito'], '/ventas/notas-credito/', { ...filtros, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []
  const filtrar = (poner) => (valor) => {
    poner(valor)
    setPagina(1)
  }

  return (
    <main className="listado">
      <CabeceraListado icono="receipt" titulo="Notas de crédito" descripcion="Devoluciones a clientes. Se emiten con «Nueva nota de crédito»: se busca el comprobante y se llena el resto.">
        <Buscador valor={busqueda} onCambio={filtrar(setBusqueda)} etiqueta="Buscar notas de crédito" placeholder="Cliente, documento o número…" />
        <input type="date" aria-label="Desde" title="Desde" value={desde} max={hasta || undefined} onChange={(e) => filtrar(setDesde)(e.target.value)} />
        <input type="date" aria-label="Hasta" title="Hasta" value={hasta} min={desde || undefined} onChange={(e) => filtrar(setHasta)(e.target.value)} />
        <Can permiso="VENTAS.NOTA_CREDITO">
          <button type="button" className="primario boton-cabecera" onClick={() => navegar('/ventas/notas-credito/nueva')}>
            <Icono nombre="agregar" tam={20} /> Nueva nota de crédito
          </button>
        </Can>
        <Can permiso="VENTAS.EXPORTAR">
          <BotonDescarga url="/ventas/notas-credito/excel/" params={sinVacios(filtros)} texto="Reporte" deshabilitado={!empresaActivaId} onError={setErrorReporte} />
        </Can>
      </CabeceraListado>
      {errorReporte && (
        <p role="alert" className="campo-error">
          {errorReporte}
        </p>
      )}
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>#</th>
                <th>Usuario</th>
                <th>N° crédito</th>
                <th>Cliente</th>
                <th>RUC/DNI</th>
                <th>Fecha</th>
                <th className="num">Asociado</th>
                <th className="num">Pendiente</th>
                <th className="num">Total</th>
                <th>Doc. que modifica</th>
                <th>Fecha doc.</th>
                <th className="centrado">
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={12} icono="receipt" titulo="No hay notas de crédito con esos filtros" descripcion="Se emiten con «Nueva nota de crédito»." />}
              {filas.map((n, i) => (
                <tr key={n.id} className="fila-clicable" onClick={() => setAbierta(n.id)}>
                  <td>{(pagina - 1) * tamano + i + 1}</td>
                  <td className="celda-suave">{n.usuario || '—'}</td>
                  <td>
                    <strong>{n.numero_completo}</strong>
                    <span className="sub-texto">{n.motivo_nombre}</span>
                  </td>
                  <td>{n.cliente_nombre || 'Clientes varios'}</td>
                  <td className="celda-suave">{n.cliente_documento || '—'}</td>
                  <td>{fechaCorta(n.fecha)}</td>
                  <td className="num">{dinero(n.asociado, n.moneda)}</td>
                  <td className="num">{dinero(n.pendiente, n.moneda)}</td>
                  <td className="num">
                    <strong>{dinero(n.total, n.moneda)}</strong>
                  </td>
                  <td className="celda-suave">
                    {n.comprobante_numero}
                    <span className="sub-texto">{n.comprobante_tipo}</span>
                  </td>
                  <td className="celda-suave">{fechaCorta(n.comprobante_fecha)}</td>
                  <td className="centrado">
                    <button
                      type="button"
                      className="accion-icono"
                      aria-label={`Abrir la nota ${n.numero_completo}`}
                      title="Ver el detalle"
                      onClick={(ev) => {
                        ev.stopPropagation()
                        setAbierta(n.id)
                      }}
                    >
                      <Icono nombre="ojo" tam={19} />
                    </button>{' '}
                    <button
                      type="button"
                      className="accion-icono"
                      aria-label={`Imprimir la nota ${n.numero_completo}`}
                      title="Imprimir"
                      onClick={(ev) => {
                        ev.stopPropagation()
                        setImpresion((previa) => ({ id: n.id, vez: (previa?.vez ?? 0) + 1 }))
                      }}
                    >
                      <Icono nombre="documento" tam={19} />
                    </button>
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
      {abierta && <NotaCreditoDetalleModal id={abierta} onCerrar={() => setAbierta(null)} />}
      {impresion && <ImpresionNotaCredito key={impresion.vez} id={impresion.id} />}
    </main>
  )
}
