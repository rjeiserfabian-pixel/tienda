import { useState } from 'react'
import { mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useAccionPlanilla, useOpcionesPlanilla, usePlanillaTrabajador, useQuitarAjuste } from '../hooks/usePlanilla'
import { decimalValido, numero, soles } from '../rrhh'
import '../rrhh.css'

const GRUPOS = [
  ['INGRESO', 'Ingresos'],
  ['DESCUENTO', 'Descuentos'],
  ['APORTE_EMPLEADOR', 'Aporte de la empresa (no se descuenta al trabajador)'],
]

/** Formulario para agregar un bono, una comisión u otro descuento a mano. */
function AjusteForm({ planilla, detalle, onListo }) {
  const { empresaActivaId } = useEmpresas()
  const opciones = useOpcionesPlanilla(empresaActivaId, true)
  const [f, setF] = useState({ concepto: '', monto: '', explicacion: '' })
  const [errores, setErrores] = useState({})
  const agregar = useAccionPlanilla(planilla, 'ajustes', { exito: 'Renglón agregado y planilla recalculada.', alExito: onListo })
  const conceptos = opciones.data?.conceptos ?? []

  const enviar = (evento) => {
    evento.preventDefault()
    if (agregar.isPending) return
    const e = {}
    if (!f.concepto) e.concepto = 'Elija el concepto.'
    if (!/^\d+(\.\d{1,2})?$/.test(f.monto) || !decimalValido(f.monto, 9_999_999.99) || Number(f.monto) <= 0) e.monto = 'Un monto mayor que cero, con hasta 2 decimales.'
    setErrores(e)
    if (Object.keys(e).length) return
    agregar.mutate(
      { detalle, concepto: Number(f.concepto), monto: f.monto, explicacion: f.explicacion.trim() },
      {
        onSuccess: () => setF({ concepto: '', monto: '', explicacion: '' }),
        onError: (error) => setErrores({ general: mensajeDeError(error) }),
      },
    )
  }

  return (
    <form onSubmit={enviar} noValidate className="rh-tarjeta">
      <h3>Agregar un bono, comisión o descuento</h3>
      <fieldset disabled={agregar.isPending} className="rh-opciones">
        <div className="rh-fila-campos">
          <Campo etiqueta="Concepto" tipo="select" requerido error={errores.concepto}>
            {(p) => (
              <select {...p} value={f.concepto} onChange={(e) => setF({ ...f, concepto: e.target.value })}>
                <option value="">Elija…</option>
                {conceptos.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.nombre} ({c.tipo === 'INGRESO' ? 'suma' : 'resta'})
                  </option>
                ))}
              </select>
            )}
          </Campo>
          <Campo etiqueta="Monto (S/)" requerido error={errores.monto}>
            {(p) => <input {...p} inputMode="decimal" maxLength={12} value={f.monto} onChange={(e) => setF({ ...f, monto: e.target.value.replace(',', '.').replace(/[^0-9.]/g, '') })} />}
          </Campo>
          <Campo etiqueta="Detalle" contador={{ actual: f.explicacion.length, max: 200 }}>
            {(p) => <input {...p} maxLength={200} value={f.explicacion} onChange={(e) => setF({ ...f, explicacion: e.target.value })} placeholder="Ej. Bono por metas de marzo" />}
          </Campo>
        </div>
      </fieldset>
      {errores.general && (
        <p role="alert" className="campo-error">
          {errores.general}
        </p>
      )}
      <div className="rh-acciones">
        <button type="submit" className="boton-cabecera primario" disabled={agregar.isPending || conceptos.length === 0}>
          {agregar.isPending ? 'Agregando…' : 'Agregar'}
        </button>
      </div>
    </form>
  )
}

/** Los renglones de un trabajador en la planilla, lo que hay que revisar de él y, si está en revisión, sus ajustes. */
export default function PlanillaTrabajadorModal({ planilla, detalle, abierta, onCerrar }) {
  const { tiene } = usePermisos()
  const puedeAjustar = abierta && tiene('RRHH.PLANILLA.CALCULAR')
  const consulta = usePlanillaTrabajador(planilla, detalle)
  const t = consulta.data
  const [error, setError] = useState('')
  const diferir = useAccionPlanilla(planilla, 'diferir', { exito: 'La cuota pasó al mes siguiente.' })
  const quitar = useQuitarAjuste(planilla, { exito: 'Renglón quitado.' })
  const ocupado = diferir.isPending || quitar.isPending
  const alError = { onError: (e) => setError(mensajeDeError(e)), onSuccess: () => setError('') }

  return (
    <Modal titulo={t?.nombre_completo ?? 'Trabajador'} subtitulo={t ? `${t.cargo || 'Sin cargo'} · ${t.regimen_nombre}` : undefined} onCerrar={onCerrar} ancho={860}>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(t)}>
        {t && (
          <div className="rh-opciones">
            {t.avisos.length > 0 && (
              <div className="rh-aviso" role="status">
                Para revisar:
                <ul>
                  {t.avisos.map((a) => (
                    <li key={a.texto}>
                      <span className="pildora" data-tono={a.nivel === 'ERROR' ? 'rojo' : 'ambar'}>
                        {a.nivel === 'ERROR' ? 'Corregir' : 'Aviso'}
                      </span>{' '}
                      {a.texto}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <dl className="rh-datos">
              <div>
                <dt>Sueldo mensual</dt>
                <dd>{soles(t.sueldo_mensual)}</dd>
              </div>
              <div>
                <dt>Días con contrato / trabajados</dt>
                <dd>
                  {t.dias_contrato} / {t.dias_laborados}
                </dd>
              </div>
              <div>
                <dt>Faltas (sin goce)</dt>
                <dd>{t.dias_falta}</dd>
              </div>
              <div>
                <dt>Horas trabajadas / extra</dt>
                <dd>
                  {numero(t.horas_trabajadas)} / {numero(t.horas_extra)}
                </dd>
              </div>
              <div>
                <dt>Pensión</dt>
                <dd>{t.sistema_pension === 'AFP' ? `AFP ${t.afp}` : t.sistema_pension || '—'}</dd>
              </div>
              <div>
                <dt>Forma de pago</dt>
                <dd>{t.metodo_pago || '—'}</dd>
              </div>
            </dl>

            {GRUPOS.map(([tipo, titulo]) => {
              const lineas = t.conceptos.filter((c) => c.tipo === tipo)
              if (lineas.length === 0) return null
              return (
                <div key={tipo} className="marco-tabla">
                  <table className="tabla-datos">
                    <caption style={{ textAlign: 'left', padding: '6px 10px' }}>
                      <strong>{titulo}</strong>
                    </caption>
                    <tbody>
                      {lineas.map((c) => (
                        <tr key={c.id}>
                          <td>
                            {c.nombre}
                            {c.manual && (
                              <>
                                {' '}
                                <span className="pildora" data-tono="azul">
                                  A mano
                                </span>
                              </>
                            )}
                            {c.explicacion && <span className="rh-sub">{c.explicacion}</span>}
                          </td>
                          <td className="derecha">{soles(c.monto)}</td>
                          <td className="derecha">
                            {puedeAjustar && c.se_puede_quitar && (
                              <button type="button" className="boton-cabecera" disabled={ocupado} onClick={() => quitar.mutate(c.id, alError)}>
                                Quitar
                              </button>
                            )}
                            {puedeAjustar && c.se_puede_diferir && (
                              <button type="button" className="boton-cabecera" disabled={ocupado} onClick={() => diferir.mutate({ linea: c.id }, alError)} title="Se descuenta el mes siguiente">
                                Pasar al mes siguiente
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            })}
            {error && (
              <p role="alert" className="campo-error">
                {error}
              </p>
            )}
            <p style={{ textAlign: 'right', margin: 0 }}>
              Ingresos {soles(t.total_ingresos)} − descuentos {soles(t.total_descuentos)} = <strong>neto a pagar {soles(t.neto)}</strong>
            </p>

            {puedeAjustar && <AjusteForm planilla={planilla} detalle={detalle} onListo={() => setError('')} />}
          </div>
        )}
      </EstadoConsulta>
    </Modal>
  )
}
