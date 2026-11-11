import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../../core/api/client'
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
import { Montos } from '../../compras/components/PorProveedor'
import { dinero, estadoVencimiento } from '../../compras/compras'
import AbonarModal from '../components/AbonarModal'
import DeudaClienteModal from '../components/DeudaClienteModal'
import '../../almacen/inventario.css'
import '../../compras/compras.css'
import '../ventas.css'

const FILTROS_VACIOS = { vencimiento: '', vence_hasta: '' }
const VISTAS = { CLIENTE: 'Por cliente', COMPROBANTE: 'Por comprobante' }

/** Totales de lo que deben los clientes, por moneda: todo, lo vencido y lo que vence en la semana. */
function Resumen({ empresaId }) {
  const consulta = useQuery({
    queryKey: ['ventas', 'por-cobrar-resumen', empresaId],
    queryFn: ({ signal }) => api.get('/ventas/por-cobrar/resumen/', { params: { empresa: empresaId }, signal }).then((r) => r.data),
    enabled: Boolean(empresaId),
  })
  if (consulta.isLoading) return <p aria-busy="true" className="celda-suave">Calculando lo que te deben…</p>
  if (consulta.isError || !consulta.data) return null
  if (consulta.data.length === 0) return <p className="celda-suave">Ningún cliente te debe nada por ahora.</p>
  return (
    <div className="cxp-resumen">
      {consulta.data.map((m) => (
        <dl className="cxp-tarjetas" key={m.moneda} aria-label={`Por cobrar en ${m.moneda === 'USD' ? 'dólares' : 'soles'}`}>
          <div>
            <dt>Total por cobrar{consulta.data.length > 1 ? ` (${m.moneda === 'USD' ? 'dólares' : 'soles'})` : ''}</dt>
            <dd>{dinero(m.saldo, m.moneda)}</dd>
            <small>
              {m.clientes} {m.clientes === 1 ? 'cliente' : 'clientes'} · {m.comprobantes} {m.comprobantes === 1 ? 'comprobante' : 'comprobantes'}
            </small>
          </div>
          <div data-tono={Number(m.vencido) > 0 ? 'rojo' : undefined}>
            <dt>Vencido</dt>
            <dd>{dinero(m.vencido, m.moneda)}</dd>
            <small>Ya debió pagarse</small>
          </div>
          <div data-tono={Number(m.por_vencer_7_dias) > 0 ? 'ambar' : undefined}>
            <dt>Vence en 7 días</dt>
            <dd>{dinero(m.por_vencer_7_dias, m.moneda)}</dd>
            <small>Para esta semana</small>
          </div>
        </dl>
      ))}
    </div>
  )
}

/** Ventas por cobrar: lo que te deben los clientes por ventas a crédito. Lo más urgente aparece primero. */
export default function VentasPorCobrarPage() {
  const { empresaActivaId } = useEmpresas()
  const navegar = useNavigate()
  const [vista, setVista] = useState('CLIENTE')
  const [cobrando, setCobrando] = useState(null)
  const [busqueda, setBusqueda] = useState('')
  const [filtros, setFiltros] = useState(FILTROS_VACIOS)
  const [filtrosAbiertos, setFiltrosAbiertos] = useState(false)
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [abierto, setAbierto] = useState(null)
  const q = useDebounce(busqueda, 400)
  const hayFiltros = Object.values(filtros).some(Boolean)
  const filtrar = (campo) => (e) => {
    setFiltros((previos) => ({ ...previos, [campo]: e.target.value }))
    setPagina(1)
  }

  const porCliente = vista === 'CLIENTE'
  const consulta = useListado(porCliente ? ['ventas', 'por-cobrar-clientes'] : ['ventas', 'por-cobrar-comprobantes'], porCliente ? '/ventas/por-cobrar/clientes/' : '/ventas/por-cobrar/comprobantes/', { empresa: empresaActivaId, q, ...filtros, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []
  const elegirVista = (v) => {
    setVista(v)
    setPagina(1)
  }

  return (
    <main className="listado">
      <CabeceraListado icono="wallet" titulo="Ventas por cobrar" descripcion="Lo que te deben los clientes por ventas a crédito. Cada empresa cobra lo suyo.">
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar deudores"
          placeholder={porCliente ? 'Cliente, DNI o RUC…' : 'Cliente o comprobante…'}
        />
        <button type="button" className={`boton-cabecera${filtrosAbiertos || hayFiltros ? ' activo' : ''}`} aria-expanded={filtrosAbiertos} onClick={() => setFiltrosAbiertos((v) => !v)}>
          <Icono nombre="filtro" tam={19} /> Filtros{hayFiltros ? ' •' : ''}
        </button>
      </CabeceraListado>

      <Resumen empresaId={empresaActivaId} />

      <div className="segmentos" role="radiogroup" aria-label="Cómo ver las deudas">
        {Object.entries(VISTAS).map(([valor, texto]) => (
          <button key={valor} type="button" role="radio" aria-checked={vista === valor} className={vista === valor ? 'activo' : undefined} onClick={() => elegirVista(valor)}>
            {texto}
          </button>
        ))}
      </div>

      {filtrosAbiertos && (
        <div className="filtros-panel" role="search">
          <label>
            Vencimiento
            <select value={filtros.vencimiento} onChange={filtrar('vencimiento')}>
              <option value="">Todos</option>
              <option value="vencidas">Solo con cuotas vencidas</option>
              <option value="por_vencer">Solo al día</option>
            </select>
          </label>
          <label>
            Vencen hasta
            <input type="date" value={filtros.vence_hasta} onChange={filtrar('vence_hasta')} />
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
        </div>
      )}

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        {porCliente ? (
          <>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Cliente</th>
                <th className="centrado">Comprobantes</th>
                <th>Próximo vencimiento</th>
                <th className="num">Vencido</th>
                <th className="num">Total adeudado</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={6} icono="wallet" titulo={hayFiltros || q ? 'Ningún cliente coincide' : 'Nadie te debe nada'} descripcion="Los clientes aparecen aquí mientras tengan ventas a crédito sin cobrar." />}
              {filas.map((f) => {
                const v = f.dias_atraso > 0 ? { texto: `Vencida hace ${f.dias_atraso} ${f.dias_atraso === 1 ? 'día' : 'días'}`, tono: 'rojo' } : estadoVencimiento(f.proximo_vencimiento)
                return (
                  <tr key={f.cliente} className="fila-clicable" onClick={() => setAbierto(f)}>
                    <td className="col-texto">
                      <strong>{f.cliente_nombre}</strong>
                      <span className="sub-texto">
                        {f.tipo_documento} {f.numero_documento}
                        {f.telefono ? ` · ${f.telefono}` : ''}
                      </span>
                    </td>
                    <td className="centrado">{f.comprobantes}</td>
                    <td className="cxp-vence">
                      {fechaCorta(f.proximo_vencimiento)}
                      <span className="pildora" data-tono={v.tono}>
                        {v.texto}
                      </span>
                    </td>
                    <td className="num cxp-vencido">
                      <Montos montos={f.montos} campo="vencido" />
                    </td>
                    <td className="num">
                      <strong>
                        <Montos montos={f.montos} campo="saldo" />
                      </strong>
                    </td>
                    <td className="centrado">
                      <button type="button" className="boton-cabecera" onClick={() => setAbierto(f)}>
                        <Icono nombre="ojo" tam={18} /> Ver deudas
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
          </>
        ) : (
          <>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Cliente</th>
                <th>Comprobante</th>
                <th>Emisión</th>
                <th>Próximo vencimiento</th>
                <th className="num">Total</th>
                <th className="num">Saldo</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={7} icono="wallet" titulo={hayFiltros || q ? 'No hay deudas con esos filtros' : 'Nadie te debe nada'} descripcion="Las ventas a crédito aparecen aquí hasta que se cobran todas sus cuotas." />}
              {filas.map((c) => {
                const v = c.dias_atraso > 0 ? { texto: `Vencida hace ${c.dias_atraso} ${c.dias_atraso === 1 ? 'día' : 'días'}`, tono: 'rojo' } : estadoVencimiento(c.proximo_vencimiento)
                return (
                  <tr key={c.id}>
                    <td className="col-texto">
                      <strong>{c.cliente_nombre}</strong>
                      {c.cliente_documento && <span className="sub-texto">{c.cliente_documento}</span>}
                    </td>
                    <td>
                      {c.numero_completo}
                      <span className="sub-texto">Venta N° {String(c.venta_numero).padStart(6, '0')}</span>
                    </td>
                    <td className="celda-suave">{fechaCorta(c.fecha)}</td>
                    <td className="cxp-vence">
                      {fechaCorta(c.proximo_vencimiento)}
                      <span className="pildora" data-tono={v.tono}>
                        {v.texto}
                      </span>
                    </td>
                    <td className="num">{dinero(c.total, c.moneda)}</td>
                    <td className="num">
                      <strong>{dinero(c.saldo, c.moneda)}</strong>
                      {Number(c.vencido) > 0 && <span className="sub-texto cxp-vencido">Vencido {dinero(c.vencido, c.moneda)}</span>}
                    </td>
                    <td className="centrado">
                      <span className="acciones-fila">
                        <button type="button" className="accion-icono ver" aria-label={`Ver la venta de ${c.numero_completo}`} title="Ver la venta" onClick={() => navegar(`/ventas/historial/${c.venta}`)}>
                          <Icono nombre="ojo" tam={19} />
                        </button>
                        <Can permiso="VENTAS.COBRAR">
                          <button type="button" className="primario compra-pagar" onClick={() => setCobrando(c)}>
                            Cobrar
                          </button>
                        </Can>
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
          </>
        )}
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
      {cobrando && <AbonarModal comprobante={cobrando} onCerrar={() => setCobrando(null)} />}
      {abierto && <DeudaClienteModal cliente={abierto} empresaId={empresaActivaId} onCerrar={() => setAbierto(null)} />}
    </main>
  )
}
