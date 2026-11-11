import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
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
import { aNumero } from '../../almacen/utilidades'
import { ESTADOS_ANTICIPO } from '../anticipos'
import AnticipoModal from '../components/AnticipoModal'
import AnularAnticipoModal from '../components/AnularAnticipoModal'
import DevolucionAnticipoModal from '../components/DevolucionAnticipoModal'
import { dinero } from '../compras'
import '../../almacen/inventario.css'

const FILTROS_VACIOS = { estado: '', desde: '', hasta: '' }

/** Anticipos a proveedores: dinero adelantado que queda como saldo a favor para pagar sus compras a crédito. */
export default function AnticiposPage() {
  const { empresaActivaId } = useEmpresas()
  const { tiene } = usePermisos()
  const puedeAnticipar = tiene('COMPRAS.ANTICIPAR')
  const puedeAnular = tiene('COMPRAS.ANULAR')
  const [params, setParams] = useSearchParams()
  const [busqueda, setBusqueda] = useState(params.get('q') ?? '')
  const [filtros, setFiltros] = useState(FILTROS_VACIOS)
  const [filtrosAbiertos, setFiltrosAbiertos] = useState(false)
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [dialogo, setDialogo] = useState(null) // { tipo: 'nuevo' | 'devolver' | 'anular', anticipo? }
  const q = useDebounce(busqueda, 400)
  const orden = params.get('orden') ?? ''

  const consulta = useListado(['compras', 'anticipos'], '/compras/anticipos/', { empresa: empresaActivaId, q, orden, ...filtros, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []
  const hayFiltros = Object.values(filtros).some(Boolean) || Boolean(orden)
  const rangoInvalido = filtros.desde && filtros.hasta && filtros.desde > filtros.hasta

  const filtrar = (campo) => (e) => {
    setFiltros((previos) => ({ ...previos, [campo]: e.target.value }))
    setPagina(1)
  }
  const limpiar = () => {
    setFiltros(FILTROS_VACIOS)
    setPagina(1)
    if (orden) setParams({}, { replace: true })
  }

  return (
    <main className="listado">
      <CabeceraListado icono="coins" titulo="Anticipos a proveedores" descripcion="Dinero que adelantas a un proveedor. Queda como saldo a favor y lo usas en «Saldos a favor» para pagar cuotas de sus compras a crédito.">
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar anticipos"
          placeholder="Código, proveedor u operación…"
        />
        <button type="button" className={`boton-cabecera${filtrosAbiertos || hayFiltros ? ' activo' : ''}`} aria-expanded={filtrosAbiertos} onClick={() => setFiltrosAbiertos((v) => !v)}>
          <Icono nombre="filtro" tam={19} /> Filtros{hayFiltros ? ' •' : ''}
        </button>
        {puedeAnticipar && (
          <button type="button" className="primario boton-cabecera" onClick={() => setDialogo({ tipo: 'nuevo' })}>
            <Icono nombre="agregar" tam={19} /> Registrar anticipo
          </button>
        )}
      </CabeceraListado>

      {filtrosAbiertos && (
        <div className="filtros-panel" role="search">
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
            <button type="button" onClick={limpiar}>
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
      {orden && <p className="celda-suave">Mostrando solo los anticipos de una orden de compra. <button type="button" onClick={limpiar}>Ver todos</button></p>}

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Código</th>
                <th>Fecha</th>
                <th>Proveedor</th>
                <th>Orden</th>
                <th className="num">Monto</th>
                <th className="num">Devuelto</th>
                <th className="num">Aplicado a compras</th>
                <th className="num">Disponible</th>
                <th>Estado</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={10} icono="coins" titulo="No hay anticipos con esos filtros" descripcion="Registra un anticipo cuando adelantes dinero a un proveedor, con o sin orden de compra." />}
              {filas.map((a) => {
                const vigente = a.estado === 'EMITIDO'
                const conSaldo = vigente && aNumero(a.disponible) > 0
                const estado = ESTADOS_ANTICIPO[a.estado] ?? { texto: a.estado, clase: '' }
                return (
                  <tr key={a.id} className={vigente ? undefined : 'anulado'}>
                    <td className="celda-suave">{a.codigo}</td>
                    <td>{fechaCorta(a.fecha)}</td>
                    <td className="col-texto">
                      {a.proveedor_nombre}
                      {a.referencia && <span className="sub-texto">Operación {a.referencia}</span>}
                    </td>
                    <td className="col-texto">{a.orden ? <Link to={`/compras/ordenes/${a.orden}`}>{a.orden_codigo}</Link> : <span className="celda-suave">—</span>}</td>
                    <td className="num">{dinero(a.monto, a.moneda)}</td>
                    <td className="num">{dinero(a.devuelto, a.moneda)}</td>
                    <td className="num">{dinero(a.aplicado, a.moneda)}</td>
                    <td className="num">
                      <strong>{dinero(a.disponible, a.moneda)}</strong>
                    </td>
                    <td>
                      <span className={`estado-pildora ${estado.clase}`}>{estado.texto}</span>
                    </td>
                    <td className="centrado">
                      <span className="acciones-fila">
                        {puedeAnticipar && conSaldo && (
                          <button type="button" onClick={() => setDialogo({ tipo: 'devolver', anticipo: a })}>
                            Devolución
                          </button>
                        )}
                        {puedeAnular && vigente && (
                          <button type="button" className="peligro" onClick={() => setDialogo({ tipo: 'anular', anticipo: a })}>
                            Anular
                          </button>
                        )}
                        {vigente && (
                          <Link to="/compras/saldos-a-favor">Usar saldo</Link>
                        )}
                      </span>
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

      {dialogo?.tipo === 'nuevo' && <AnticipoModal onCerrar={() => setDialogo(null)} />}
      {dialogo?.tipo === 'devolver' && <DevolucionAnticipoModal anticipo={dialogo.anticipo} onCerrar={() => setDialogo(null)} />}
      {dialogo?.tipo === 'anular' && <AnularAnticipoModal anticipo={dialogo.anticipo} onCerrar={() => setDialogo(null)} />}
    </main>
  )
}
