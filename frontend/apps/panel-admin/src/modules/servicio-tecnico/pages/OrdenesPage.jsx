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
import ImpresionOrden from '../components/ImpresionOrden'
import { useConfiguracionServicio } from '../hooks/useConfiguracionServicio'
import { diasDesde, ESTADOS_ORDEN, PRIORIDADES } from '../servicio'
import '../../almacen/inventario.css'
import '../servicio-tecnico.css'

const RUTA = '/servicio-tecnico/ordenes'
const FILTROS_VACIOS = { estado: 'abiertas', tecnico: '', prioridad: '', atrasadas: '', sin_recoger: '', garantia: '', desde: '', hasta: '' }
const VACIO = []

/** Órdenes de servicio de la empresa: el equipo de cada cliente, en qué estado está y quién lo trabaja. */
export default function OrdenesPage({ mias = false }) {
  const navegar = useNavigate()
  const { empresaActivaId } = useEmpresas()
  const [busqueda, setBusqueda] = useState('')
  const [filtros, setFiltros] = useState(FILTROS_VACIOS)
  const [filtrosAbiertos, setFiltrosAbiertos] = useState(false)
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [impresion, setImpresion] = useState(null) // { id, vez }: cada clic en Imprimir vuelve a montarla
  const q = useDebounce(busqueda, 400)
  const tecnicos = useConfiguracionServicio(empresaActivaId).data?.tecnicos ?? VACIO

  const consulta = useListado(['servicio', 'ordenes'], '/servicio-tecnico/ordenes/', { empresa: empresaActivaId, q, ...filtros, ...(mias ? { mias: 1 } : {}), page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? VACIO
  const hayFiltros = Object.entries(filtros).some(([campo, valor]) => valor !== FILTROS_VACIOS[campo])
  const rangoInvalido = filtros.desde && filtros.hasta && filtros.desde > filtros.hasta
  const filtrar = (campo) => (e) => {
    setFiltros((previos) => ({ ...previos, [campo]: e.target.value }))
    setPagina(1)
  }

  return (
    <main className="listado">
      <CabeceraListado icono="wrench" titulo={mias ? 'Mis órdenes' : 'Órdenes de servicio'} descripcion={mias ? 'Los equipos que tienes asignados: ábrelos para diagnosticar y avanzar su estado.' : 'Los equipos que los clientes dejan en el taller: en qué estado están, quién los trabaja y cuándo se prometió entregarlos.'}>
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar órdenes"
          placeholder="Código, cliente, equipo o serie…"
        />
        <button type="button" className={`boton-cabecera${filtrosAbiertos || hayFiltros ? ' activo' : ''}`} aria-expanded={filtrosAbiertos} onClick={() => setFiltrosAbiertos((v) => !v)}>
          <Icono nombre="filtro" tam={19} /> Filtros{hayFiltros ? ' •' : ''}
        </button>
        {!mias && <Can permiso="SERVICIOS.RECEPCIONAR">
          <button type="button" className="primario boton-cabecera" onClick={() => navegar('/servicio-tecnico/ingreso')}>
            <Icono nombre="agregar" tam={20} /> Registrar ingreso
          </button>
        </Can>}
      </CabeceraListado>

      {filtrosAbiertos && (
        <div className="filtros-panel" role="search">
          <label>
            Estado
            <select value={filtros.estado} onChange={filtrar('estado')}>
              <option value="abiertas">Abiertas (sin entregar)</option>
              <option value="">Todas</option>
              {Object.entries(ESTADOS_ORDEN).map(([valor, e]) => (
                <option key={valor} value={valor}>
                  {e.texto}
                </option>
              ))}
            </select>
          </label>
          {!mias && (
          <label>
            Técnico
            <select value={filtros.tecnico} onChange={filtrar('tecnico')}>
              <option value="">Todos</option>
              {tecnicos.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.nombre}
                </option>
              ))}
            </select>
          </label>
          )}
          <label>
            Prioridad
            <select value={filtros.prioridad} onChange={filtrar('prioridad')}>
              <option value="">Todas</option>
              {PRIORIDADES.map(([valor, texto]) => (
                <option key={valor} value={valor}>
                  {texto}
                </option>
              ))}
            </select>
          </label>
          <label>
            Entrega
            <select value={filtros.atrasadas} onChange={filtrar('atrasadas')}>
              <option value="">Todas</option>
              <option value="1">Solo atrasadas</option>
            </select>
          </label>
          <label>
            Sin recoger
            <select value={filtros.sin_recoger} onChange={filtrar('sin_recoger')}>
              <option value="">Todos</option>
              <option value="1">Listos hace más de 30 días</option>
            </select>
          </label>
          <label>
            Garantía
            <select value={filtros.garantia} onChange={filtrar('garantia')}>
              <option value="">Todas</option>
              <option value="1">Solo reingresos por garantía</option>
            </select>
          </label>
          <label>
            Ingresó desde
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
                <th>Orden</th>
                <th>Cliente</th>
                <th>Equipo y falla</th>
                <th>Estado</th>
                <th>Técnico</th>
                <th>Prometida</th>
                <th className="servicio-col-acciones">
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={7} icono="wrench" titulo="No hay órdenes con esos filtros" descripcion="Registra el ingreso de un equipo para crear la primera orden." />}
              {filas.map((o) => {
                const estado = ESTADOS_ORDEN[o.estado]
                const dias = diasDesde(o.fecha_ingreso)
                return (
                  <tr key={o.id} className="fila-clicable" onClick={() => navegar(`${RUTA}/${o.id}`)}>
                    <td>
                      <strong>{o.codigo}</strong>
                      <span className="sub-texto">{fechaCorta(o.fecha_ingreso)}</span>
                      {o.prioridad === 'URGENTE' && (
                        <span className="pildora" data-tono="rojo">
                          Urgente
                        </span>
                      )}
                      {o.es_garantia && (
                        <span className="pildora" data-tono="cian" title={`Reingreso por garantía de ${o.reingreso_de_codigo}`}>
                          Garantía
                        </span>
                      )}
                    </td>
                    <td className="col-texto">
                      {o.cliente_nombre}
                      <span className="sub-texto">{o.cliente_documento}</span>
                    </td>
                    <td className="col-texto">
                      {o.equipo_descripcion}
                      <span className="sub-texto">{o.falla_reportada.length > 70 ? `${o.falla_reportada.slice(0, 70)}…` : o.falla_reportada}</span>
                    </td>
                    <td>
                      <span className="pildora" data-tono={estado?.tono ?? 'gris'}>
                        {estado?.texto ?? o.estado_nombre}
                      </span>
                      {Number(o.adelanto_disponible) > 0 && (
                        <span className="pildora" data-tono={['NO_APROBADO', 'SIN_SOLUCION', 'ABANDONADO'].includes(o.estado) ? 'rojo' : 'azul'} title="Dinero que el cliente dejó por adelantado y todavía no se descontó ni se devolvió">
                          Adelanto S/ {o.adelanto_disponible}
                        </span>
                      )}
                      {o.por_abandonar && (
                        <span className="pildora" data-tono="rosa" title="Lleva más de 30 días esperando: ya se puede dar por abandonado si se avisó al cliente">
                          Por abandonar · {o.dias_en_estado} días
                        </span>
                      )}
                      {o.estado !== 'ENTREGADO' && dias >= 1 && <span className="sub-texto">{dias === 1 ? '1 día en el taller' : `${dias} días en el taller`}</span>}
                    </td>
                    <td>{o.tecnico_nombre || <span className="celda-suave">Sin asignar</span>}</td>
                    <td>
                      {o.fecha_promesa ? fechaCorta(o.fecha_promesa) : <span className="celda-suave">—</span>}
                      {o.atrasada && <span className="sub-texto servicio-atrasada">Atrasada</span>}
                    </td>
                    <td className="servicio-col-acciones">
                      <button
                        type="button"
                        className="accion-icono"
                        aria-label={`Imprimir la hoja de ingreso ${o.codigo}`}
                        title="Imprimir"
                        onClick={(ev) => {
                          ev.stopPropagation()
                          setImpresion((previa) => ({ id: o.id, vez: (previa?.vez ?? 0) + 1 }))
                        }}
                      >
                        <Icono nombre="documento" tam={19} />
                      </button>
                      <button
                        type="button"
                        className="accion-icono"
                        aria-label={`Abrir la orden ${o.codigo}`}
                        title="Ver"
                        onClick={(ev) => {
                          ev.stopPropagation()
                          navegar(`${RUTA}/${o.id}`)
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
      {impresion && <ImpresionOrden key={impresion.vez} id={impresion.id} />}
    </main>
  )
}
