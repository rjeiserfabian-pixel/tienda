import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../../../core/api/client'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import PedidoDetalle from '../components/PedidoDetalle'
import { ESTADOS_PEDIDO, fechaHora, MODALIDADES_PEDIDO, PESTANAS_PEDIDOS, soles } from '../pedidos'
import '../tienda.css'
import '../pedidos.css'

const CLAVE_LISTA = ['tienda', 'pedidos']
const FILTROS_VACIOS = { modalidad: '', desde: '', hasta: '' }

/** Pedidos de la tienda en línea: qué hay que preparar, qué salió y qué requiere atención. */
export default function PedidosTiendaPage() {
  const [params, setParams] = useSearchParams()
  const abierto = params.get('pedido')
  const [pestana, setPestana] = useState('por_atender')
  const [soloAtencion, setSoloAtencion] = useState(false)
  const [busqueda, setBusqueda] = useState('')
  const [filtros, setFiltros] = useState(FILTROS_VACIOS)
  const [filtrosAbiertos, setFiltrosAbiertos] = useState(false)
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const q = useDebounce(busqueda, 400)

  const resumen = useQuery({
    queryKey: ['tienda', 'pedidos-resumen'],
    queryFn: ({ signal }) => api.get('/tienda/admin/pedidos/resumen/', { signal }).then((r) => r.data),
    refetchInterval: 60_000,
  })
  const consulta = useListado(
    CLAVE_LISTA,
    '/tienda/admin/pedidos/',
    { grupo: soloAtencion ? '' : pestana, requiere_atencion: soloAtencion ? '1' : '', q, ...filtros, page: pagina, page_size: tamano },
    { refetchInterval: 60_000 },
  )
  const filas = consulta.data?.results ?? []
  const hayFiltros = Object.values(filtros).some(Boolean)
  const rangoInvalido = filtros.desde && filtros.hasta && filtros.desde > filtros.hasta
  const conteos = resumen.data?.grupos ?? {}
  const atencion = resumen.data?.requieren_atencion ?? 0

  const filtrar = (campo) => (e) => {
    setFiltros((previos) => ({ ...previos, [campo]: e.target.value }))
    setPagina(1)
  }
  const elegirPestana = (valor) => {
    setPestana(valor)
    setSoloAtencion(false)
    setPagina(1)
  }
  const abrir = (numero) => setParams({ pedido: numero }, { replace: false })
  const cerrar = () => setParams({}, { replace: true })

  return (
    <main className="listado tienda-pagina pedidos-pagina">
      <CabeceraListado icono="cart" titulo="Pedidos de la tienda" descripcion="Lo que los clientes compraron en la tienda en línea: prepáralo, envíalo o déjalo listo para recoger.">
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar pedidos"
          placeholder="N.° de pedido, cliente, documento…"
        />
        <button type="button" className={`boton-cabecera${filtrosAbiertos || hayFiltros ? ' activo' : ''}`} aria-expanded={filtrosAbiertos} onClick={() => setFiltrosAbiertos((v) => !v)}>
          <Icono nombre="filtro" tam={19} /> Filtros{hayFiltros ? ' •' : ''}
        </button>
      </CabeceraListado>

      <div className="pedidos-barra">
        <div className="tienda-segmentos" role="group" aria-label="Estado de los pedidos">
          {PESTANAS_PEDIDOS.map((t) => (
            <button key={t.valor || 'todos'} type="button" aria-pressed={!soloAtencion && pestana === t.valor} onClick={() => elegirPestana(t.valor)}>
              {t.texto}
              {t.valor && conteos[t.valor] > 0 && <span className="pedidos-conteo">{conteos[t.valor]}</span>}
            </button>
          ))}
        </div>
        {atencion > 0 && (
          <button type="button" className={`pedidos-atencion-boton${soloAtencion ? ' activo' : ''}`} aria-pressed={soloAtencion} onClick={() => { setSoloAtencion((v) => !v); setPagina(1) }}>
            <Icono nombre="bell" tam={18} /> Requieren atención <b>{atencion}</b>
          </button>
        )}
      </div>

      {filtrosAbiertos && (
        <div className="filtros-panel" role="search">
          <label>
            Entrega
            <select value={filtros.modalidad} onChange={filtrar('modalidad')}>
              <option value="">Todas</option>
              {Object.entries(MODALIDADES_PEDIDO).map(([valor, texto]) => (
                <option key={valor} value={valor}>
                  {texto}
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
            <button type="button" onClick={() => { setFiltros(FILTROS_VACIOS); setPagina(1) }}>
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
          <table className="tabla-datos tabla-pedidos">
            <thead>
              <tr>
                <th>Pedido</th>
                <th>Fecha</th>
                <th>Cliente</th>
                <th>Entrega</th>
                <th className="num">Total</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={6} icono="cart" titulo="No hay pedidos aquí" descripcion="Cuando un cliente compre en la tienda, su pedido aparecerá en esta lista." />}
              {filas.map((p) => {
                const estado = ESTADOS_PEDIDO[p.estado] ?? { texto: p.estado, tono: 'gris' }
                return (
                  <tr
                    key={p.numero}
                    className={`fila-clicable${p.requiere_atencion ? ' pedido-atencion-fila' : ''}`}
                    tabIndex={0}
                    onClick={() => abrir(p.numero)}
                    onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), abrir(p.numero))}
                  >
                    <td data-etiqueta="Pedido" className="celda-suave">
                      <b>{p.numero}</b>
                    </td>
                    <td data-etiqueta="Fecha">{fechaHora(p.pagado_en ?? p.creado_en)}</td>
                    <td data-etiqueta="Cliente" className="col-texto">
                      {p.cliente}
                      <span className="sub-texto">{p.correo}</span>
                    </td>
                    <td data-etiqueta="Entrega">
                      {MODALIDADES_PEDIDO[p.modalidad]}
                      {p.modalidad === 'RECOJO' && p.punto && <span className="sub-texto">{p.punto}</span>}
                      {p.seguimiento && <span className="sub-texto">{p.seguimiento}</span>}
                    </td>
                    <td data-etiqueta="Total" className="num">
                      {soles(p.total)}
                    </td>
                    <td data-etiqueta="Estado">
                      <span className="pildora" data-tono={estado.tono}>
                        {estado.texto}
                      </span>
                      {p.motivo_atencion && <span className="sub-texto pedido-motivo">{p.motivo_atencion}</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <Paginacion pagina={pagina} tamano={tamano} total={consulta.data?.count ?? 0} onPagina={setPagina} onTamano={(t) => { setTamano(t); setPagina(1) }} />
      </EstadoConsulta>

      {abierto && <PedidoDetalle numero={abierto} onCerrar={cerrar} claveLista={CLAVE_LISTA} />}
    </main>
  )
}
