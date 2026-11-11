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
import GuiaDetalleModal from '../components/GuiaDetalleModal'
import ImpresionGuia from '../components/ImpresionGuia'
import { origenDeGuia } from '../ventas'
import '../../almacen/inventario.css'
import '../ventas.css'

/** Quién la lleva: el tipo de transporte y, debajo, la empresa de transporte o la placa con su conductor. */
const celdaTransporte = (g) => (
  <>
    {g.modalidad === '01' ? 'Público' : 'Privado'}
    <span className="sub-texto">{g.modalidad === '01' ? g.transportista_nombre : [g.placa, g.conductor_nombre].filter(Boolean).join(' · ') || 'Sin vehículo (M1 o L)'}</span>
  </>
)

/**
 * Guías de remisión: lo que viaja hacia los clientes, con su transporte. Cada fila se abre o se imprime desde
 * sus botones; «Reporte» baja a Excel lo que se ve (con los mismos filtros).
 */
export default function GuiasRemisionPage() {
  const navegar = useNavigate()
  const { empresaActivaId } = useEmpresas()
  const [busqueda, setBusqueda] = useState('')
  const [estado, setEstado] = useState('')
  const [desde, setDesde] = useState('')
  const [hasta, setHasta] = useState('')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [abierta, setAbierta] = useState(null)
  const [impresion, setImpresion] = useState(null) // { id, vez }: cada clic en Imprimir vuelve a montarla
  const [errorReporte, setErrorReporte] = useState('')
  const q = useDebounce(busqueda, 400)
  const filtros = { empresa: empresaActivaId, q, estado, desde, hasta }
  const consulta = useListado(['ventas', 'guias'], '/ventas/guias-remision/', { ...filtros, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []
  const filtrar = (poner) => (valor) => {
    poner(valor)
    setPagina(1)
  }

  return (
    <main className="listado">
      <CabeceraListado icono="truck" titulo="Guías de remisión" descripcion="El documento que acompaña la mercadería. Las de una venta se emiten con «Nueva guía de remisión»; las de un traslado entre almacenes, desde Movimientos, con el botón de guía de su traspaso.">
        <Buscador valor={busqueda} onCambio={filtrar(setBusqueda)} etiqueta="Buscar guías" placeholder="Cliente, documento, número o placa…" />
        <select aria-label="Estado" value={estado} onChange={(e) => filtrar(setEstado)(e.target.value)}>
          <option value="">Todas</option>
          <option value="EMITIDO">Vigentes</option>
          <option value="ANULADO">Anuladas</option>
        </select>
        <input type="date" aria-label="Desde" title="Desde" value={desde} max={hasta || undefined} onChange={(e) => filtrar(setDesde)(e.target.value)} />
        <input type="date" aria-label="Hasta" title="Hasta" value={hasta} min={desde || undefined} onChange={(e) => filtrar(setHasta)(e.target.value)} />
        <Can permiso="VENTAS.GUIA_REMISION">
          <button type="button" className="primario boton-cabecera" onClick={() => navegar('/ventas/guias-remision/nueva')}>
            <Icono nombre="agregar" tam={20} /> Nueva guía de remisión
          </button>
        </Can>
        <Can permiso="VENTAS.EXPORTAR">
          <BotonDescarga url="/ventas/guias-remision/excel/" params={sinVacios(filtros)} texto="Reporte" deshabilitado={!empresaActivaId} onError={setErrorReporte} />
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
                <th>Emisión</th>
                <th>Guía</th>
                <th>Destinatario</th>
                <th>Comprobante</th>
                <th>Llega a</th>
                <th>Traslado</th>
                <th>Transporte</th>
                <th>Carga</th>
                <th className="col-ajustada">Estado</th>
                <th className="col-acciones">
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={10} icono="truck" titulo="No hay guías de remisión con esos filtros" descripcion="Se emiten con «Nueva guía de remisión»." />}
              {filas.map((g) => (
                <tr key={g.id} className={`fila-clicable${g.estado === 'ANULADO' ? ' anulado' : ''}`} onClick={() => setAbierta(g.id)}>
                  <td>{fechaCorta(g.fecha_emision)}</td>
                  <td>
                    <strong>{g.numero_completo}</strong>
                    <span className="sub-texto">{g.usuario || '—'}</span>
                  </td>
                  <td className="col-texto">
                    {g.destinatario_nombre}
                    {g.destinatario_documento && (
                      <span className="sub-texto">
                        {g.destinatario_tipo_documento} {g.destinatario_documento}
                      </span>
                    )}
                  </td>
                  <td className="celda-suave">
                    {origenDeGuia(g).corto}
                    <span className="sub-texto">{origenDeGuia(g).tipo}</span>
                  </td>
                  <td className="celda-suave">{g.punto_llegada}</td>
                  <td>{fechaCorta(g.fecha_traslado)}</td>
                  <td>{celdaTransporte(g)}</td>
                  <td className="celda-suave">
                    {g.bultos} bulto(s)
                    <span className="sub-texto">{Number(g.peso_kg) > 0 ? `${Number(g.peso_kg)} kg` : 'Sin peso'}</span>
                  </td>
                  <td className="col-ajustada">
                    <span className="pildora" data-tono={g.estado === 'ANULADO' ? 'rojo' : 'verde'}>
                      {g.estado === 'ANULADO' ? 'Anulada' : 'Vigente'}
                    </span>
                  </td>
                  <td className="col-acciones">
                    <button
                      type="button"
                      className="accion-icono"
                      aria-label={`Imprimir la guía ${g.numero_completo}`}
                      title="Imprimir"
                      onClick={(ev) => {
                        ev.stopPropagation()
                        setImpresion((previa) => ({ id: g.id, vez: (previa?.vez ?? 0) + 1 }))
                      }}
                    >
                      <Icono nombre="documento" tam={19} />
                    </button>{' '}
                    <button
                      type="button"
                      className="accion-icono"
                      aria-label={`Abrir la guía ${g.numero_completo}`}
                      title="Ver"
                      onClick={(ev) => {
                        ev.stopPropagation()
                        setAbierta(g.id)
                      }}
                    >
                      <Icono nombre="ojo" tam={19} />
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
      {abierta && <GuiaDetalleModal id={abierta} onCerrar={() => setAbierta(null)} />}
      {impresion && <ImpresionGuia key={impresion.vez} id={impresion.id} />}
    </main>
  )
}
