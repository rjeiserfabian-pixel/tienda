import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../../../core/api/client'
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
import { fechaCorta } from '../../almacen/inventario'
import AnularMovimientoCajaModal from '../components/AnularMovimientoCajaModal'
import MovimientoModal from '../components/MovimientoModal'
import VoucherModal from '../components/VoucherModal'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import { dinero, origen } from '../caja'
import '../../almacen/inventario.css'
import '../caja.css'

const FILTROS_VACIOS = { tipo: '', medio: '', tipo_cuenta: '', estado: '', origen: '', sin_bancarizar: '', desde: '', hasta: '' }

/** Libro de ingresos y egresos de la empresa; con una caja o cuenta elegida muestra el saldo que dejó cada movimiento. */
export default function MovimientosCajaPage() {
  const { empresaActivaId } = useEmpresas()
  const { tiene } = usePermisos()
  const [params, setParams] = useSearchParams()
  const cuenta = params.get('cuenta') ?? ''
  const [busqueda, setBusqueda] = useState('')
  const [filtros, setFiltros] = useState(FILTROS_VACIOS)
  const [vista, setVista] = useState('') // '' = el turno abierto; 'todo' = todo el historial; o el id de una sesión
  const [filtrosAbiertos, setFiltrosAbiertos] = useState(false)
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [dialogo, setDialogo] = useState(null) // { tipo: 'nuevo', movimiento: 'INGRESO' | 'EGRESO' } o { tipo: 'anular', movimiento }
  const q = useDebounce(busqueda, 400)
  const metodos = useOpciones('/mantenimiento/medios-pago/', { estado: 'ACTIVO' }).data ?? []
  const puedeAnular = tiene('CAJA.MOVIMIENTOS.ANULAR')

  const saldos = useQuery({
    queryKey: ['caja', 'saldos', empresaActivaId],
    queryFn: ({ signal }) => api.get('/caja/saldos/', { params: { empresa: empresaActivaId }, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId),
  })
  const cuentas = saldos.data?.cuentas ?? []
  const elegida = cuentas.find((c) => String(c.cuenta) === cuenta)
  // En una caja de efectivo, por defecto solo se ve el turno abierto: lo de días anteriores es historial.
  const esCaja = elegida?.tipo === 'CAJA'
  const sesiones = useQuery({
    queryKey: ['caja', 'sesiones', 'de-la-caja', empresaActivaId, cuenta],
    queryFn: ({ signal }) => api.get('/caja/sesiones/', { params: { empresa: empresaActivaId, cuenta, page_size: 30 }, signal }).then((r) => r.data.results),
    enabled: Boolean(empresaActivaId) && esCaja,
  })
  const conFechas = Boolean(filtros.desde || filtros.hasta)
  const abierta = elegida?.sesion?.id ?? ''
  const sesion = !esCaja || conFechas || vista === 'todo' ? '' : vista || abierta
  const consulta = useListado(['caja', 'movimientos'], '/caja/movimientos/', { empresa: empresaActivaId, cuenta, sesion, q, ...filtros, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []
  const hayFiltros = Object.values(filtros).some(Boolean)
  const rangoInvalido = filtros.desde && filtros.hasta && filtros.desde > filtros.hasta
  const filtrar = (campo) => (e) => {
    setFiltros((previos) => ({ ...previos, [campo]: e.target.value }))
    setPagina(1)
  }
  const elegirCuenta = (valor) => {
    setParams(valor ? { cuenta: valor } : {})
    setVista('')
    setPagina(1)
  }
  const dia = (atras) => {
    const d = new Date()
    d.setDate(d.getDate() - atras)
    return d.toLocaleDateString('en-CA')
  }
  const verDia = (atras) => {
    setFiltros((previos) => ({ ...previos, desde: dia(atras), hasta: dia(atras) }))
    setPagina(1)
  }
  const fechaHora = (iso) => new Date(iso).toLocaleString('es-PE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })

  return (
    <main className="listado">
      <CabeceraListado icono="swap" titulo="Movimientos" descripcion="Cada línea es dinero que entró (Ingreso) o salió (Egreso), con su método de pago y su caja o cuenta. Los pagos de compras aparecen solos.">
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar movimientos"
          placeholder="Detalle, operación, concepto…"
        />
        <button type="button" className={`boton-cabecera${filtrosAbiertos || hayFiltros ? ' activo' : ''}`} aria-expanded={filtrosAbiertos} onClick={() => setFiltrosAbiertos((v) => !v)}>
          <Icono nombre="filtro" tam={19} /> Filtros{hayFiltros ? ' •' : ''}
        </button>
        <Can permiso="CAJA.MOVIMIENTOS.CREAR">
          <button type="button" className="boton-cabecera" onClick={() => setDialogo({ tipo: 'nuevo', movimiento: 'EGRESO' })}>
            <Icono nombre="agregar" tam={19} /> Egreso
          </button>
          <button type="button" className="primario boton-cabecera" onClick={() => setDialogo({ tipo: 'nuevo', movimiento: 'INGRESO' })}>
            <Icono nombre="agregar" tam={20} /> Ingreso
          </button>
        </Can>
      </CabeceraListado>

      <div className="filtros-panel" role="search">
        <label>
          Caja o cuenta
          <select value={cuenta} onChange={(e) => elegirCuenta(e.target.value)}>
            <option value="">Todas</option>
            {cuentas.map((c) => (
              <option key={c.cuenta} value={c.cuenta}>
                {c.nombre} ({c.moneda === 'USD' ? 'US$' : 'S/'})
              </option>
            ))}
          </select>
        </label>
        {esCaja && (
          <label>
            Mostrar
            <select
              value={conFechas ? 'fechas' : vista || (abierta ? String(abierta) : 'todo')}
              onChange={(e) => {
                setFiltros((previos) => ({ ...previos, desde: '', hasta: '' }))
                setVista(e.target.value === String(abierta) ? '' : e.target.value)
                setPagina(1)
              }}
            >
              {conFechas && <option value="fechas">Las fechas elegidas</option>}
              {abierta && <option value={abierta}>Turno abierto (N° {elegida.sesion.numero})</option>}
              {(sesiones.data ?? [])
                .filter((s) => s.id !== abierta)
                .map((s) => (
                  <option key={s.id} value={s.id}>
                    Turno N° {s.numero} · {fechaHora(s.abierta_en)}
                  </option>
                ))}
              <option value="todo">Todo el historial</option>
            </select>
          </label>
        )}
        {elegida && (
          <p className="celda-suave">
            Saldo actual: <strong>{dinero(elegida.saldo, elegida.moneda)}</strong>
          </p>
        )}
        <div role="group" aria-label="Atajos de fecha">
          <button type="button" onClick={() => verDia(0)}>
            Hoy
          </button>{' '}
          <button type="button" onClick={() => verDia(1)}>
            Ayer
          </button>
        </div>
      </div>
      {esCaja && !abierta && !conFechas && vista === '' && (
        <p className="celda-suave" role="status">
          Esta caja está cerrada: se muestra todo su historial. Ábrela en «Saldos» para empezar un turno nuevo.
        </p>
      )}

      {filtrosAbiertos && (
        <div className="filtros-panel" role="search">
          <label>
            Tipo
            <select value={filtros.tipo} onChange={filtrar('tipo')}>
              <option value="">Ingresos y egresos</option>
              <option value="INGRESO">Ingresos</option>
              <option value="EGRESO">Egresos</option>
            </select>
          </label>
          <label>
            Método de pago
            <select value={filtros.medio} onChange={filtrar('medio')}>
              <option value="">Todos</option>
              {metodos.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.nombre}
                </option>
              ))}
            </select>
          </label>
          <label>
            Tipo de cuenta
            <select value={filtros.tipo_cuenta} onChange={filtrar('tipo_cuenta')}>
              <option value="">Todas</option>
              <option value="CAJA">Cajas de efectivo</option>
              <option value="BANCO">Cuentas de banco</option>
              <option value="BILLETERA">Billeteras digitales</option>
            </select>
          </label>
          <label>
            Origen
            <select value={filtros.origen} onChange={filtrar('origen')}>
              <option value="">Todos</option>
              <option value="manual">Hechos a mano</option>
              <option value="automatico">Generados por el sistema</option>
            </select>
          </label>
          <label>
            Efectivo grande
            <select value={filtros.sin_bancarizar} onChange={filtrar('sin_bancarizar')}>
              <option value="">Todos</option>
              <option value="1">Solo sin bancarizar</option>
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
                <th>Fecha</th>
                <th>N°</th>
                <th>Caja o cuenta</th>
                <th>Método</th>
                <th>Concepto</th>
                <th>Origen</th>
                <th className="num">Ingreso</th>
                <th className="num">Egreso</th>
                {cuenta && <th className="num">Saldo</th>}
                <th>Estado</th>
                <th className="centrado">
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={cuenta ? 11 : 10} icono="swap" titulo="No hay movimientos con esos filtros" descripcion="Registra un ingreso o un egreso, o paga una compra: aparecerá aquí." />}
              {filas.map((m) => {
                const o = origen(m.origen_tipo)
                return (
                  <tr key={m.id} className={m.estado === 'ANULADO' ? 'anulado' : undefined}>
                    <td>{fechaCorta(m.fecha)}</td>
                    <td className="celda-suave">{String(m.numero).padStart(6, '0')}</td>
                    <td className="col-texto">
                      {m.cuenta_nombre}
                      <span className="sub-texto">{m.cuenta_tipo_nombre}</span>
                    </td>
                    <td>
                      <span className="pildora" data-tono={m.cuenta_tipo === 'CAJA' ? 'verde' : m.cuenta_tipo === 'BANCO' ? 'azul' : 'morado'}>
                        {m.medio_nombre}
                      </span>
                    </td>
                    <td className="col-texto">
                      {m.concepto_nombre}
                      {(m.glosa || m.referencia) && (
                        <span className="sub-texto">
                          {m.glosa}
                          {m.referencia ? ` · Operación ${m.referencia}` : ''}
                        </span>
                      )}
                      {m.estado === 'ANULADO' && m.motivo_anulacion && <span className="sub-texto">Anulado: {m.motivo_anulacion}</span>}
                      {m.sin_bancarizar && <span className="pildora" data-tono="naranja" title="Llega al límite de bancarización y se hizo en efectivo">Sin bancarizar</span>}
                    </td>
                    <td>
                      <span className="pildora" data-tono={o.tono}>
                        {o.texto}
                      </span>
                    </td>
                    <td className="num caja-ingreso">{m.tipo === 'INGRESO' ? dinero(m.monto, m.moneda) : ''}</td>
                    <td className="num caja-egreso">{m.tipo === 'EGRESO' ? dinero(m.monto, m.moneda) : ''}</td>
                    {cuenta && <td className="num">{m.saldo_despues === null ? '—' : dinero(m.saldo_despues, m.moneda)}</td>}
                    <td>{m.estado === 'ANULADO' ? <span className="estado-pildora inactivo">Anulado</span> : <span className="estado-pildora activo">Vigente</span>}</td>
                    <td className="centrado">
                      <button type="button" className="accion-icono" aria-label={`Vouchers del movimiento ${m.numero}`} title={m.adjuntos_cantidad ? `${m.adjuntos_cantidad} vouchers` : 'Vouchers'} onClick={() => setDialogo({ tipo: 'voucher', movimiento: m })}>
                        <Icono nombre="camara" tam={19} />
                        {m.adjuntos_cantidad > 0 && <span className="clip">{m.adjuntos_cantidad}</span>}
                      </button>
                      {puedeAnular && m.puede_anularse && (
                        <button type="button" className="accion-icono peligro-suave" aria-label={`Anular el movimiento ${m.numero}`} title="Anular" onClick={() => setDialogo({ tipo: 'anular', movimiento: m })}>
                          <Icono nombre="apagar" tam={19} />
                        </button>
                      )}
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

      {dialogo?.tipo === 'nuevo' && <MovimientoModal tipoInicial={dialogo.movimiento} umbral={saldos.data?.umbral_bancarizacion} cuentas={cuentas} cuentaInicial={cuenta} onCerrar={() => setDialogo(null)} />}
      {dialogo?.tipo === 'voucher' && <VoucherModal movimiento={dialogo.movimiento} puedeSubir={tiene('CAJA.MOVIMIENTOS.CREAR')} onCerrar={() => setDialogo(null)} />}
      {dialogo?.tipo === 'anular' && <AnularMovimientoCajaModal movimiento={dialogo.movimiento} onCerrar={() => setDialogo(null)} />}
    </main>
  )
}
