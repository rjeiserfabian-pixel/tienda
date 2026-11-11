import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import BotonVolver from '../../../shared/components/BotonVolver'
import Can from '../../../shared/components/Can'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import { api, mensajeDeError } from '../../../core/api/client'
import { mensajeDeErrorDescarga } from '../../../shared/utils/descarga'
import BoletaVistaPrevia from '../components/BoletaVistaPrevia'
import { AnularPagoModal, PagarModal } from '../components/PlanillaPagoModal'
import PlanillaAccionModal from '../components/PlanillaAccionModal'
import PlanillaTrabajadorModal from '../components/PlanillaTrabajadorModal'
import { useAccionPlanilla, usePlanilla } from '../hooks/usePlanilla'
import { fechaCorta, mesAnio, soles } from '../rrhh'
import '../rrhh.css'

/** Una planilla mensual: totales, lo que hay que corregir y una fila por trabajador. */
export default function PlanillaPage() {
  const { id } = useParams()
  const navegar = useNavigate()
  const consulta = usePlanilla(id)
  const p = consulta.data
  const [modal, setModal] = useState(null) // 'cerrar' | 'reabrir' | 'descartar'
  const [abierto, setAbierto] = useState(null)
  const [error, setError] = useState('')
  const [pagando, setPagando] = useState(false)
  const [boleta, setBoleta] = useState(null)
  const [anulando, setAnulando] = useState(null)
  const [aviso, setAviso] = useState('')
  const [bajando, setBajando] = useState(false)
  const recalcular = useAccionPlanilla(id, 'recalcular', { exito: 'Planilla recalculada.' })
  const enRevision = p?.estado === 'BORRADOR'
  const porPagar = (p?.trabajadores ?? []).filter((t) => !t.pago && Number(t.neto) > 0).length

  // El archivo de transferencias lleva cuentas: se pide con la sesión y se entrega como descarga.
  const bajarArchivo = async () => {
    setBajando(true)
    setError('')
    setAviso('')
    try {
      const r = await api.get(`/rrhh/planillas/${id}/archivo-banco/`, { responseType: 'blob', timeout: 60_000 })
      const nombre = /filename="([^"]+)"/.exec(r.headers['content-disposition'] ?? '')?.[1] ?? 'transferencias.csv'
      const objeto = URL.createObjectURL(r.data)
      const enlace = document.createElement('a')
      enlace.href = objeto
      enlace.download = nombre
      document.body.append(enlace)
      enlace.click()
      enlace.remove()
      setTimeout(() => URL.revokeObjectURL(objeto), 10_000)
      const omitidos = decodeURIComponent(r.headers['x-omitidos'] ?? '')
      if (omitidos) setAviso(`No se incluyeron por no tener banco y cuenta registrados: ${omitidos}.`)
    } catch (e) {
      setError(await mensajeDeErrorDescarga(e))
    } finally {
      setBajando(false)
    }
  }

  return (
    <main className="listado">
      <BotonVolver ruta="/rrhh/planillas" texto="Planillas" />
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(p)}>
        {p && (
          <>
            <header className="rh-tarjeta">
              <header>
                <h2 style={{ margin: 0, textTransform: 'capitalize' }}>Planilla de {mesAnio(p.periodo)}</h2>
                <span className="pildora mas" data-tono={p.estado === 'CERRADA' ? 'verde' : 'ambar'}>
                  {p.estado === 'CERRADA' ? 'Cerrada' : 'En revisión'}
                </span>
              </header>
              <dl className="rh-datos">
                <div>
                  <dt>Trabajadores</dt>
                  <dd>{p.num_trabajadores}</dd>
                </div>
                <div>
                  <dt>Ingresos</dt>
                  <dd>{soles(p.total_ingresos)}</dd>
                </div>
                <div>
                  <dt>Descuentos</dt>
                  <dd>{soles(p.total_descuentos)}</dd>
                </div>
                <div>
                  <dt>Neto a pagar</dt>
                  <dd>
                    <strong>{soles(p.total_neto)}</strong>
                  </dd>
                </div>
                <div>
                  <dt>EsSalud (aporte de la empresa)</dt>
                  <dd>{soles(p.total_aportes)}</dd>
                </div>
                {!enRevision && (
                  <div>
                    <dt>Pagado</dt>
                    <dd>
                      {soles(p.total_pagado)} ({p.num_pagados} de {p.trabajadores.length})
                    </dd>
                  </div>
                )}
              </dl>
              {p.estado === 'CERRADA' && p.motivo_reapertura && <p className="celda-suave">Reabierta antes: {p.motivo_reapertura}</p>}
              <div className="rh-acciones">
                {enRevision && (
                  <Can permiso="RRHH.PLANILLA.CALCULAR">
                    <button type="button" className="boton-cabecera" disabled={recalcular.isPending} onClick={() => recalcular.mutate(undefined, { onError: (e) => setError(mensajeDeError(e)), onSuccess: () => setError('') })}>
                      {recalcular.isPending ? 'Recalculando…' : 'Recalcular'}
                    </button>
                    <button type="button" className="boton-cabecera" onClick={() => setModal('descartar')}>
                      Descartar
                    </button>
                  </Can>
                )}
                {enRevision && (
                  <Can permiso="RRHH.PLANILLA.CERRAR">
                    <button type="button" className="boton-cabecera primario" disabled={!p.puede_cerrar} title={p.puede_cerrar ? undefined : 'Corrija primero lo que está en rojo'} onClick={() => setModal('cerrar')}>
                      Cerrar planilla
                    </button>
                  </Can>
                )}
                {!enRevision && porPagar > 0 && (
                  <Can permiso="RRHH.PLANILLA.PAGAR">
                    <button type="button" className="boton-cabecera primario" onClick={() => setPagando(true)}>
                      Pagar sueldos ({porPagar})
                    </button>
                  </Can>
                )}
                {!enRevision && (
                  <Can permiso="RRHH.PLANILLA.ARCHIVO_BANCO">
                    <button type="button" className="boton-cabecera" disabled={bajando} onClick={bajarArchivo}>
                      {bajando ? 'Generando…' : 'Archivo del banco'}
                    </button>
                  </Can>
                )}
                {!enRevision && (
                  <Can permiso="RRHH.PLANILLA.REABRIR">
                    <button type="button" className="boton-cabecera" onClick={() => setModal('reabrir')}>
                      Reabrir
                    </button>
                  </Can>
                )}
              </div>
              {error && (
                <p role="alert" className="campo-error">
                  {error}
                </p>
              )}
              {aviso && (
                <p className="rh-aviso" role="status">
                  {aviso}
                </p>
              )}
            </header>

            {enRevision && p.avisos.length > 0 && (
              <div className="rh-aviso" role="status">
                Antes de cerrar hay que corregir:
                <ul>
                  {p.avisos.map((a) => (
                    <li key={a.texto}>{a.texto}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="marco-tabla">
              <table className="tabla-datos">
                <thead>
                  <tr>
                    <th>Trabajador</th>
                    <th className="derecha">Días / faltas</th>
                    <th className="derecha">Ingresos</th>
                    <th className="derecha">Descuentos</th>
                    <th className="derecha">Neto</th>
                    <th>{enRevision ? 'Revisar' : 'Pago'}</th>
                    <th className="centrado">Ver</th>
                  </tr>
                </thead>
                <tbody>
                  {p.trabajadores.length === 0 && <FilaVacia columnas={7} icono="users" titulo="Sin trabajadores" descripcion="No hay trabajadores con contrato en este mes." />}
                  {p.trabajadores.map((t) => (
                    <tr key={t.id} className="rh-fila-clicable" onClick={() => setAbierto(t.id)}>
                      <td>
                        <strong>{t.nombre_completo}</strong>
                        <span className="rh-sub">{t.cargo || t.regimen_nombre}</span>
                      </td>
                      <td className="derecha">
                        {t.dias_laborados} / {t.dias_falta}
                      </td>
                      <td className="derecha">{soles(t.total_ingresos)}</td>
                      <td className="derecha">{soles(t.total_descuentos)}</td>
                      <td className="derecha">
                        <strong>{soles(t.neto)}</strong>
                      </td>
                      <td>
                        {!enRevision &&
                          (t.pago ? (
                            <span className="pildora mas" data-tono="verde">
                              Pagado {fechaCorta(t.pago.fecha)}
                            </span>
                          ) : (
                            <span className="pildora mas" data-tono="ambar">
                              Por pagar
                            </span>
                          ))}
                        {t.num_errores > 0 && (
                          <span className="pildora mas" data-tono="rojo">
                            {t.num_errores} por corregir
                          </span>
                        )}{' '}
                        {t.num_avisos > 0 && (
                          <span className="pildora mas" data-tono="ambar">
                            {t.num_avisos} aviso(s)
                          </span>
                        )}
                      </td>
                      <td className="centrado">
                        <span className="acciones-fila">
                          <button
                            type="button"
                            className="accion-icono"
                            aria-label={`Boleta de pago de ${t.nombre_completo}`}
                            title="Boleta de pago"
                            onClick={(evento) => {
                              evento.stopPropagation()
                              setBoleta(t.id)
                            }}
                          >
                            <Icono nombre="documento" tam={19} />
                          </button>
                          {!enRevision && t.pago && (
                            <Can permiso="RRHH.PLANILLA.PAGAR">
                              <button
                                type="button"
                                className="accion-icono"
                                aria-label={`Anular el pago de ${t.nombre_completo}`}
                                title="Anular el pago"
                                onClick={(evento) => {
                                  evento.stopPropagation()
                                  setAnulando(t)
                                }}
                              >
                                <Icono nombre="cerrar" tam={19} />
                              </button>
                            </Can>
                          )}
                          <button
                            type="button"
                            className="accion-icono ver"
                            aria-label={`Ver el detalle de ${t.nombre_completo}`}
                            title="Ver el detalle"
                            onClick={(evento) => {
                              evento.stopPropagation()
                              setAbierto(t.id)
                            }}
                          >
                            <Icono nombre="ojo" tam={19} />
                          </button>
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </EstadoConsulta>
      {modal && p && <PlanillaAccionModal planilla={p} tipo={modal} onCerrar={() => setModal(null)} onListo={() => navegar('/rrhh/planillas')} />}
      {pagando && p && <PagarModal planilla={p} onCerrar={() => setPagando(false)} />}
      {anulando && p && <AnularPagoModal planilla={p} trabajador={anulando} onCerrar={() => setAnulando(null)} />}
      {boleta && <BoletaVistaPrevia planilla={id} detalle={boleta} onCerrar={() => setBoleta(null)} />}
      {abierto && <PlanillaTrabajadorModal planilla={id} detalle={abierto} abierta={enRevision} onCerrar={() => setAbierto(null)} />}
    </main>
  )
}
