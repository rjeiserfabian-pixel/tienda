import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
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
import AnularTransferenciaModal from '../components/AnularTransferenciaModal'
import TransferenciaModal from '../components/TransferenciaModal'
import { CLASES, dinero } from '../caja'
import '../../almacen/inventario.css'
import '../caja.css'

const FILTROS_VACIOS = { clase: '', estado: '', desde: '', hasta: '' }

/** Depósitos, retiros y transferencias entre cajas y cuentas, con el cambio y los costos del banco. */
export default function TransferenciasPage() {
  const { empresaActivaId } = useEmpresas()
  const { tiene } = usePermisos()
  const [busqueda, setBusqueda] = useState('')
  const [filtros, setFiltros] = useState(FILTROS_VACIOS)
  const [filtrosAbiertos, setFiltrosAbiertos] = useState(false)
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [dialogo, setDialogo] = useState(null) // { tipo: 'nuevo', clase } o { tipo: 'anular', transferencia }
  const q = useDebounce(busqueda, 400)
  const puedeAnular = tiene('CAJA.MOVIMIENTOS.ANULAR')

  const saldos = useQuery({
    queryKey: ['caja', 'saldos', empresaActivaId],
    queryFn: ({ signal }) => api.get('/caja/saldos/', { params: { empresa: empresaActivaId }, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId),
  })
  const consulta = useListado(['caja', 'transferencias'], '/caja/transferencias/', { empresa: empresaActivaId, q, ...filtros, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []
  const hayFiltros = Object.values(filtros).some(Boolean)
  const rangoInvalido = filtros.desde && filtros.hasta && filtros.desde > filtros.hasta
  const filtrar = (campo) => (e) => {
    setFiltros((previos) => ({ ...previos, [campo]: e.target.value }))
    setPagina(1)
  }

  return (
    <main className="listado">
      <CabeceraListado icono="swap" titulo="Transferencias" descripcion="Depósitos al banco, retiros a la caja y dinero que pasa de una cuenta a otra, incluso de soles a dólares.">
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar transferencias"
          placeholder="Cuenta, operación, detalle…"
        />
        <button type="button" className={`boton-cabecera${filtrosAbiertos || hayFiltros ? ' activo' : ''}`} aria-expanded={filtrosAbiertos} onClick={() => setFiltrosAbiertos((v) => !v)}>
          <Icono nombre="filtro" tam={19} /> Filtros{hayFiltros ? ' •' : ''}
        </button>
        <Can permiso="CAJA.TRANSFERIR">
          <button type="button" className="primario boton-cabecera" onClick={() => setDialogo({ tipo: 'nuevo', clase: 'TRANSFERENCIA' })}>
            <Icono nombre="agregar" tam={20} /> Mover dinero
          </button>
        </Can>
      </CabeceraListado>

      {filtrosAbiertos && (
        <div className="filtros-panel" role="search">
          <label>
            Clase
            <select value={filtros.clase} onChange={filtrar('clase')}>
              <option value="">Todas</option>
              {Object.entries(CLASES).map(([valor, { titulo }]) => (
                <option key={valor} value={valor}>
                  {titulo}
                </option>
              ))}
            </select>
          </label>
          <label>
            Estado
            <select value={filtros.estado} onChange={filtrar('estado')}>
              <option value="">Todos</option>
              <option value="EMITIDO">Vigentes</option>
              <option value="ANULADO">Anuladas</option>
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
                <th>Clase</th>
                <th>Sale de</th>
                <th>Entra a</th>
                <th className="num">Salió</th>
                <th className="num">Entró</th>
                <th className="num">Costos</th>
                <th>Estado</th>
                <th className="centrado">
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={10} icono="swap" titulo="No hay transferencias con esos filtros" descripcion="Mueve dinero entre tus cajas y cuentas: aparecerá aquí." />}
              {filas.map((t) => {
                const costos = Number(t.comision) + Number(t.itf)
                return (
                  <tr key={t.id} className={t.estado === 'ANULADO' ? 'anulado' : undefined}>
                    <td>{fechaCorta(t.fecha)}</td>
                    <td className="celda-suave">{String(t.numero).padStart(6, '0')}</td>
                    <td>{t.clase_nombre}</td>
                    <td className="col-texto">
                      {t.origen_nombre}
                      {t.entre_empresas && <span className="sub-texto">{t.empresa_nombre}</span>}
                    </td>
                    <td className="col-texto">
                      {t.destino_nombre}
                      {t.entre_empresas && <span className="sub-texto">{t.empresa_destino_nombre}</span>}
                      {(t.glosa || t.referencia) && (
                        <span className="sub-texto">
                          {t.glosa}
                          {t.referencia ? ` · Operación ${t.referencia}` : ''}
                        </span>
                      )}
                      {t.estado === 'ANULADO' && t.motivo_anulacion && <span className="sub-texto">Anulada: {t.motivo_anulacion}</span>}
                    </td>
                    <td className="num caja-egreso">{dinero(t.monto_origen, t.origen_moneda)}</td>
                    <td className="num caja-ingreso">
                      {dinero(t.monto_destino, t.destino_moneda)}
                      {t.tipo_cambio && <span className="sub-texto">Cambio {t.tipo_cambio}</span>}
                    </td>
                    <td className="num">{costos > 0 ? dinero(costos.toFixed(2), t.origen_moneda) : ''}</td>
                    <td>{t.estado === 'ANULADO' ? <span className="estado-pildora inactivo">Anulada</span> : <span className="estado-pildora activo">Vigente</span>}</td>
                    <td className="centrado">
                      {puedeAnular && t.estado !== 'ANULADO' && (
                        <button type="button" className="accion-icono peligro-suave" aria-label={`Anular la transferencia ${t.numero}`} title="Anular" onClick={() => setDialogo({ tipo: 'anular', transferencia: t })}>
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

      {dialogo?.tipo === 'nuevo' && <TransferenciaModal claseInicial={dialogo.clase} cuentas={saldos.data?.cuentas ?? []} onCerrar={() => setDialogo(null)} />}
      {dialogo?.tipo === 'anular' && <AnularTransferenciaModal transferencia={dialogo.transferencia} onCerrar={() => setDialogo(null)} />}
    </main>
  )
}
