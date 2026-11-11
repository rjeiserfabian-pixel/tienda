import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, mensajeDeError } from '../../../core/api/client'
import Can from '../../../shared/components/Can'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useListado } from '../../../shared/hooks/useListado'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaCorta } from '../../almacen/inventario'
import AccionConNotaModal from '../components/AccionConNotaModal'
import CandidatosModal from '../components/CandidatosModal'
import RegistrarPartidaModal from '../components/RegistrarPartidaModal'
import { dinero, ESTADOS_CONCILIACION, estadoDeDiferencia } from '../caja'
import '../../almacen/inventario.css'
import '../caja.css'

const VISTAS = [
  ['pendiente', 'Por conciliar'],
  ['conciliada', 'Conciliadas'],
  ['', 'Todas'],
]

/** Un estado de cuenta: sus líneas, lo que falta explicar y las acciones para conciliarlo. */
export default function ConciliacionDetallePage() {
  const { id } = useParams()
  const navegar = useNavigate()
  const { tiene } = usePermisos()
  const [vista, setVista] = useState('pendiente')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(50)
  const [dialogo, setDialogo] = useState(null) // { tipo, linea? }
  const [aviso, setAviso] = useState('')

  const detalle = useQuery({
    queryKey: ['caja', 'extracto', id],
    queryFn: ({ signal }) => api.get(`/caja/extractos/${id}/`, { signal }).then((r) => r.data),
  })
  const e = detalle.data
  const lineas = useListado(['caja', 'extracto-lineas', id], `/caja/extractos/${id}/lineas/`, { estado: vista, page: pagina, page_size: tamano })
  const filas = lineas.data?.results ?? []

  const automatica = useMutacion({
    mutationFn: () => api.post(`/caja/extractos/${id}/automatica/`).then((r) => r.data),
    invalidar: [['caja']],
    exito: (r) => (r.unidas ? `Se unieron ${r.unidas} líneas.` : 'No había líneas con una sola coincidencia clara.'),
    avisarError: false,
  })
  const deshacer = useMutacion({
    mutationFn: (linea) => api.post(`/caja/lineas-extracto/${linea}/deshacer/`).then((r) => r.data),
    invalidar: [['caja']],
    exito: 'Conciliación deshecha.',
    avisarError: false,
  })

  const abierto = e?.estado === 'ABIERTO'
  const puedeGestionar = tiene('CAJA.CONCILIACION.GESTIONAR')
  const r = e?.resumen
  const diferencia = r ? estadoDeDiferencia(r.diferencia) : null
  const estado = e && ESTADOS_CONCILIACION[e.estado]

  return (
    <main className="listado">
      <header className="cabecera-ficha">
        <button type="button" className="boton-cabecera" onClick={() => navegar('/caja/conciliacion')}>
          <Icono nombre="chevron" tam={18} /> Conciliación
        </button>
        {e && (
          <div>
            <h1>
              {e.cuenta_nombre} · {fechaCorta(e.desde)} – {fechaCorta(e.hasta)}
            </h1>
            <p className="celda-suave">
              Estado de cuenta {String(e.numero).padStart(6, '0')} · {e.archivo_nombre} · importado por {e.importado_por_nombre}{' '}
              <span className={`estado-pildora ${estado.clase}`}>{estado.texto}</span>
            </p>
          </div>
        )}
      </header>

      <EstadoConsulta consulta={detalle} hayDatos={Boolean(e)}>
        {e && (
          <>
            <dl className="conteo-resumen" aria-label="Resumen de la conciliación">
              <div>
                <dt>Líneas conciliadas</dt>
                <dd>
                  {r.conciliadas} de {r.lineas}
                </dd>
              </div>
              <div data-tono={r.pendientes ? 'falta' : undefined}>
                <dt>Por conciliar</dt>
                <dd>{r.pendientes}</dd>
              </div>
              <div>
                <dt>Saldo según el banco</dt>
                <dd>{r.saldo_banco === null ? '—' : dinero(r.saldo_banco, e.moneda)}</dd>
              </div>
              <div>
                <dt>Saldo según el libro</dt>
                <dd>{dinero(r.saldo_libros, e.moneda)}</dd>
                <dt>al {fechaCorta(e.hasta)}</dt>
              </div>
              <div>
                <dt>En el libro, sin banco aún</dt>
                <dd>{dinero(r.libro_sin_banco, e.moneda)}</dd>
                <dt>{r.libro_sin_banco_cantidad} movimientos en tránsito</dt>
              </div>
              <div data-tono={diferencia.tipo === 'difiere' ? 'falta' : diferencia.tipo === 'cuadra' ? 'sobra' : undefined}>
                <dt>Diferencia sin explicar</dt>
                <dd>{r.diferencia === null ? '—' : dinero(r.diferencia, e.moneda)}</dd>
                <dt>{diferencia.texto}</dt>
              </div>
            </dl>
            {e.estado === 'CERRADO' && (
              <p className="celda-suave">
                Conciliado por {e.cerrado_por_nombre} el {fechaCorta(e.cerrado_en)}.{e.nota_cierre ? ` Nota: ${e.nota_cierre}` : ''}
              </p>
            )}

            <div className="barra-acciones">
              <div className="segmentos" role="radiogroup" aria-label="Qué líneas ver">
                {VISTAS.map(([valor, texto]) => (
                  <button
                    key={texto}
                    type="button"
                    role="radio"
                    aria-checked={vista === valor}
                    className={vista === valor ? 'activo' : undefined}
                    onClick={() => {
                      setVista(valor)
                      setPagina(1)
                    }}
                  >
                    {texto}
                  </button>
                ))}
              </div>
              <Can permiso="CAJA.CONCILIACION.GESTIONAR">
                {abierto && (
                  <>
                    <button type="button" className="boton-cabecera" disabled={automatica.isPending || r.pendientes === 0} onClick={() => automatica.mutate(undefined, { onError: (er) => setAviso(mensajeDeError(er)) })}>
                      <Icono nombre="scan" tam={18} /> {automatica.isPending ? 'Buscando…' : 'Conciliar automáticamente'}
                    </button>
                    <button type="button" className="boton-cabecera" onClick={() => setDialogo({ tipo: 'descartar' })}>
                      <Icono nombre="papelera" tam={18} /> Descartar
                    </button>
                  </>
                )}
              </Can>
              <Can permiso="CAJA.CONCILIACION.CERRAR">
                {abierto ? (
                  <button type="button" className="primario boton-cabecera" onClick={() => setDialogo({ tipo: 'cerrar' })}>
                    <Icono nombre="lock" tam={18} /> Cerrar conciliación
                  </button>
                ) : (
                  <button type="button" className="boton-cabecera" onClick={() => setDialogo({ tipo: 'reabrir' })}>
                    <Icono nombre="reactivar" tam={18} /> Reabrir
                  </button>
                )}
              </Can>
            </div>
            {aviso && (
              <p role="alert" className="campo-error">
                {aviso}
              </p>
            )}

            <EstadoConsulta consulta={lineas} hayDatos={Boolean(lineas.data)}>
              <div className="marco-tabla">
                <table className="tabla-datos">
                  <thead>
                    <tr>
                      <th>Fecha</th>
                      <th>Descripción del banco</th>
                      <th className="num">Abono</th>
                      <th className="num">Cargo</th>
                      <th>En el libro</th>
                      <th className="centrado">
                        <span className="sr-only">Acciones</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {filas.length === 0 && <FilaVacia columnas={6} icono="scan" titulo={vista === 'pendiente' ? 'No queda nada por conciliar' : 'No hay líneas'} descripcion={vista === 'pendiente' ? 'Cuando el saldo cuadre, cierra la conciliación.' : 'Cambia el filtro para ver otras líneas.'} />}
                    {filas.map((l) => (
                      <tr key={l.id}>
                        <td>{fechaCorta(l.fecha)}</td>
                        <td className="col-texto">
                          {l.descripcion || '—'}
                          {l.referencia && <span className="sub-texto">Operación {l.referencia}</span>}
                        </td>
                        <td className="num caja-ingreso">{Number(l.monto) > 0 ? dinero(l.monto, e.moneda) : ''}</td>
                        <td className="num caja-egreso">{Number(l.monto) < 0 ? dinero(Math.abs(Number(l.monto)), e.moneda) : ''}</td>
                        <td className="col-texto">
                          {l.movimiento ? (
                            <>
                              <span className="estado-pildora activo">Conciliada</span>
                              <span className="sub-texto">
                                N° {String(l.movimiento_numero).padStart(6, '0')} · {l.movimiento_concepto} · {l.union_nombre.toLowerCase()}
                              </span>
                            </>
                          ) : (
                            <span className="estado-pildora pendiente">Por conciliar</span>
                          )}
                        </td>
                        <td className="centrado">
                          {puedeGestionar && abierto && !l.movimiento && (
                            <>
                              <button type="button" className="accion-icono" aria-label="Buscar el movimiento del libro" title="Buscar el movimiento" onClick={() => setDialogo({ tipo: 'buscar', linea: l })}>
                                <Icono nombre="buscar" tam={19} />
                              </button>
                              <button type="button" className="accion-icono" aria-label="Registrar en el libro" title="Registrar en el libro" onClick={() => setDialogo({ tipo: 'registrar', linea: l })}>
                                <Icono nombre="agregar" tam={19} />
                              </button>
                            </>
                          )}
                          {puedeGestionar && abierto && l.movimiento && (
                            <button type="button" className="accion-icono peligro-suave" aria-label="Deshacer la conciliación" title="Deshacer" disabled={deshacer.isPending} onClick={() => deshacer.mutate(l.id, { onError: (er) => setAviso(mensajeDeError(er)) })}>
                              <Icono nombre="apagar" tam={19} />
                            </button>
                          )}
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
              total={lineas.data?.count ?? 0}
              onPagina={setPagina}
              onTamano={(t) => {
                setTamano(t)
                setPagina(1)
              }}
            />
          </>
        )}
      </EstadoConsulta>

      {dialogo?.tipo === 'buscar' && <CandidatosModal linea={dialogo.linea} moneda={e.moneda} onCerrar={() => setDialogo(null)} />}
      {dialogo?.tipo === 'registrar' && <RegistrarPartidaModal linea={dialogo.linea} moneda={e.moneda} onCerrar={() => setDialogo(null)} />}
      {dialogo?.tipo === 'cerrar' && (
        <AccionConNotaModal
          url={`/caja/extractos/${id}/cerrar/`}
          titulo="Cerrar la conciliación"
          subtitulo={`${e.cuenta_nombre} · ${fechaCorta(e.desde)} – ${fechaCorta(e.hasta)}`}
          descripcion={r.diferencia !== null && Number(r.diferencia) !== 0 ? `Los saldos no cuadran (diferencia de ${dinero(r.diferencia, e.moneda)}). Explica el motivo para poder cerrar.` : 'El banco ya no tiene líneas sin explicar. Al cerrar, sus uniones quedan fijas hasta que se reabra.'}
          campo="nota"
          etiqueta="Nota"
          requerido={r.diferencia !== null && Number(r.diferencia) !== 0}
          placeholder="Opcional"
          boton="Cerrar conciliación"
          ocupado="Cerrando…"
          exito="Conciliación cerrada."
          onCerrar={() => setDialogo(null)}
        />
      )}
      {dialogo?.tipo === 'reabrir' && <AccionConNotaModal url={`/caja/extractos/${id}/reabrir/`} titulo="Reabrir la conciliación" descripcion="Podrás deshacer o cambiar uniones. Después hay que cerrarla otra vez." campo="motivo" etiqueta="Motivo" requerido placeholder="Ej. Faltaba registrar una comisión" boton="Reabrir" ocupado="Reabriendo…" exito="Conciliación reabierta." onCerrar={() => setDialogo(null)} />}
      {dialogo?.tipo === 'descartar' && <AccionConNotaModal url={`/caja/extractos/${id}/descartar/`} titulo="Descartar el estado de cuenta" descripcion="Se quita este estado de cuenta, por ejemplo si importaste el archivo equivocado. Solo se puede si no hay líneas conciliadas." boton="Descartar" ocupado="Descartando…" exito="Estado de cuenta descartado." peligro alExito={() => navegar('/caja/conciliacion')} onCerrar={() => setDialogo(null)} />}
    </main>
  )
}
