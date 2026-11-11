import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../../core/api/client'
import Can from '../../../shared/components/Can'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useListado } from '../../../shared/hooks/useListado'
import ContarSesionModal from '../components/ContarSesionModal'
import ReabrirSesionModal from '../components/ReabrirSesionModal'
import SesionDetalleModal from '../components/SesionDetalleModal'
import { dinero, ESTADOS_SESION } from '../caja'
import '../../almacen/inventario.css'
import '../caja.css'

const FILTROS_VACIOS = { cuenta: '', estado: '', desde: '', hasta: '' }
const fechaHora = (iso) => (iso ? new Date(iso).toLocaleString('es-PE', { dateStyle: 'short', timeStyle: 'short' }) : '—')

/** Turnos de cada caja de efectivo: quién la abrió, cuánto esperaba el sistema, cuánto se contó y si cuadró. */
export default function SesionesCajaPage() {
  const { empresaActivaId } = useEmpresas()
  const [filtros, setFiltros] = useState(FILTROS_VACIOS)
  const [filtrosAbiertos, setFiltrosAbiertos] = useState(false)
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [dialogo, setDialogo] = useState(null) // { tipo: 'detalle' | 'cerrar' | 'reabrir', sesion }

  const cajas = useQuery({
    queryKey: ['caja', 'saldos', empresaActivaId],
    queryFn: ({ signal }) => api.get('/caja/saldos/', { params: { empresa: empresaActivaId }, signal }).then((r) => r.data.cuentas),
    enabled: Boolean(empresaActivaId),
  })
  const consulta = useListado(['caja', 'sesiones'], '/caja/sesiones/', { empresa: empresaActivaId, ...filtros, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []
  const hayFiltros = Object.values(filtros).some(Boolean)
  const rangoInvalido = filtros.desde && filtros.hasta && filtros.desde > filtros.hasta
  const filtrar = (campo) => (e) => {
    setFiltros((previos) => ({ ...previos, [campo]: e.target.value }))
    setPagina(1)
  }
  // Solo la última sesión de cada caja se puede reabrir, y solo si la caja no tiene otra abierta.
  const ultimaDe = new Map()
  for (const s of filas) if (!ultimaDe.has(s.cuenta)) ultimaDe.set(s.cuenta, s.id)

  return (
    <main className="listado">
      <CabeceraListado icono="reloj" titulo="Sesiones de caja" descripcion="Cada turno de una caja de efectivo: se abre, se cuenta el dinero y se cierra. Las diferencias quedan registradas.">
        <button type="button" className={`boton-cabecera${filtrosAbiertos || hayFiltros ? ' activo' : ''}`} aria-expanded={filtrosAbiertos} onClick={() => setFiltrosAbiertos((v) => !v)}>
          <Icono nombre="filtro" tam={19} /> Filtros{hayFiltros ? ' •' : ''}
        </button>
      </CabeceraListado>

      {filtrosAbiertos && (
        <div className="filtros-panel" role="search">
          <label>
            Caja
            <select value={filtros.cuenta} onChange={filtrar('cuenta')}>
              <option value="">Todas</option>
              {(cajas.data ?? [])
                .filter((c) => c.tipo === 'CAJA')
                .map((c) => (
                  <option key={c.cuenta} value={c.cuenta}>
                    {c.nombre}
                  </option>
                ))}
            </select>
          </label>
          <label>
            Estado
            <select value={filtros.estado} onChange={filtrar('estado')}>
              <option value="">Todas</option>
              <option value="ABIERTA">Abiertas</option>
              <option value="CERRADA">Cerradas</option>
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
                <th>N°</th>
                <th>Caja</th>
                <th>Responsable</th>
                <th>Abrió</th>
                <th>Cerró</th>
                <th className="num">Esperado</th>
                <th className="num">Contado</th>
                <th className="num">Diferencia</th>
                <th>Estado</th>
                <th className="centrado">
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={10} icono="reloj" titulo="Todavía no hay sesiones" descripcion="Abre una caja desde «Saldos»: su turno aparecerá aquí." />}
              {filas.map((s) => {
                const abierta = s.estado === 'ABIERTA'
                const e = ESTADOS_SESION[s.estado]
                const diferencia = Number(s.diferencia)
                return (
                  <tr key={s.id}>
                    <td className="celda-suave">{String(s.numero).padStart(6, '0')}</td>
                    <td>{s.cuenta_nombre}</td>
                    <td>{s.responsable_nombre}</td>
                    <td>{fechaHora(s.abierta_en)}</td>
                    <td>{fechaHora(s.cerrada_en)}</td>
                    <td className="num">{dinero(abierta ? s.esperado_actual : s.esperado_cierre, s.moneda)}</td>
                    <td className="num">{abierta ? '—' : dinero(s.contado_cierre, s.moneda)}</td>
                    <td className={`num ${diferencia > 0 ? 'caja-ingreso' : diferencia < 0 ? 'caja-egreso' : ''}`}>{abierta ? '—' : diferencia === 0 ? 'Cuadra' : dinero(s.diferencia, s.moneda)}</td>
                    <td>
                      <span className={`estado-pildora ${e.clase}`}>{e.texto}</span>
                    </td>
                    <td className="centrado">
                      <button type="button" className="accion-icono" aria-label={`Ver la sesión ${s.numero}`} title="Ver el detalle" onClick={() => setDialogo({ tipo: 'detalle', sesion: s })}>
                        <Icono nombre="ojo" tam={19} />
                      </button>
                      {abierta && (
                        <Can permiso="CAJA.SESIONES.ABRIR">
                          <button type="button" className="accion-icono" aria-label={`Cerrar la sesión ${s.numero}`} title="Contar y cerrar" onClick={() => setDialogo({ tipo: 'cerrar', sesion: s })}>
                            <Icono nombre="lock" tam={19} />
                          </button>
                        </Can>
                      )}
                      {!abierta && ultimaDe.get(s.cuenta) === s.id && (
                        <Can permiso="CAJA.SESIONES.REABRIR">
                          <button type="button" className="accion-icono" aria-label={`Reabrir la sesión ${s.numero}`} title="Reabrir" onClick={() => setDialogo({ tipo: 'reabrir', sesion: s })}>
                            <Icono nombre="reactivar" tam={19} />
                          </button>
                        </Can>
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

      {dialogo?.tipo === 'detalle' && <SesionDetalleModal sesionId={dialogo.sesion.id} onCerrar={() => setDialogo(null)} />}
      {dialogo?.tipo === 'cerrar' && <ContarSesionModal sesionId={dialogo.sesion.id} modo="cerrar" onCerrar={() => setDialogo(null)} />}
      {dialogo?.tipo === 'reabrir' && <ReabrirSesionModal sesion={dialogo.sesion} onCerrar={() => setDialogo(null)} />}
    </main>
  )
}
