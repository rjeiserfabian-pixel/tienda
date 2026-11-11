import { useState } from 'react'
import { codigoDeError, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { useAccionCts, useCalcularCts, useDepositarCts, useDescartarCts, useOpcionesDeposito } from '../hooks/useCts'
import { soles } from '../rrhh'
import '../rrhh.css'

const hoy = new Date()
const hoyIso = () => hoy.toLocaleDateString('en-CA')

/** Calcula la CTS de un semestre que ya terminó (mayo: nov-abr; noviembre: may-oct). */
export function CalcularCtsModal({ onCerrar, onCreado }) {
  const { empresaActivaId } = useEmpresas()
  // Lo habitual es el último semestre terminado.
  const mayoEsReciente = hoy.getMonth() + 1 >= 5 && hoy.getMonth() + 1 < 11
  const [f, setF] = useState({ anio: String(hoy.getMonth() + 1 >= 11 ? hoy.getFullYear() : hoy.getFullYear() - (mayoEsReciente ? 0 : 1)), periodo: mayoEsReciente ? 'MAYO' : 'NOVIEMBRE' })
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')
  const calcular = useCalcularCts({ exito: 'CTS calculada. Revísela antes de depositarla.', alExito: (c) => (onCreado ? onCreado(c) : onCerrar()) })

  const enviar = (evento) => {
    evento.preventDefault()
    if (calcular.isPending) return
    const e = {}
    if (!/^\d{4}$/.test(f.anio)) e.anio = 'Indique un año válido.'
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return
    calcular.mutate(
      { empresa: empresaActivaId, anio: Number(f.anio), periodo: f.periodo },
      {
        onError: (error) => {
          const delServidor = erroresDeCampo(error)
          setErrores(delServidor)
          setGeneral(Object.keys(delServidor).length > 0 && codigoDeError(error) === 'validacion' ? 'Revise los datos marcados.' : mensajeDeError(error))
        },
      },
    )
  }

  return (
    <Modal titulo="Calcular CTS" subtitulo="Se calcula con los contratos, el sueldo, las faltas y la gratificación del semestre." onCerrar={onCerrar} ancho={500}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={calcular.isPending} className="rh-opciones">
          <div className="rh-fila-campos">
            <Campo etiqueta="Depósito de" tipo="select" requerido error={errores.periodo}>
              {(p) => (
                <select {...p} value={f.periodo} onChange={(e) => setF({ ...f, periodo: e.target.value })}>
                  <option value="MAYO">Mayo (noviembre a abril)</option>
                  <option value="NOVIEMBRE">Noviembre (mayo a octubre)</option>
                </select>
              )}
            </Campo>
            <Campo etiqueta="Año" requerido error={errores.anio}>
              {(p) => <input {...p} inputMode="numeric" maxLength={4} value={f.anio} onChange={(e) => setF({ ...f, anio: e.target.value.replace(/\D/g, '') })} />}
            </Campo>
          </div>
        </fieldset>
        {general && (
          <p role="alert" className="campo-error">
            {general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={calcular.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={calcular.isPending}>
            {calcular.isPending ? 'Calculando…' : 'Calcular'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

/** Registra el depósito de la CTS: un egreso de la caja o cuenta elegida por cada trabajador. */
export function DepositarCtsModal({ cts, onCerrar }) {
  const opciones = useOpcionesDeposito(cts.id)
  const [f, setF] = useState({ fecha: hoyIso(), cuenta: '', medio: '', referencia: '' })
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')
  const cuentas = opciones.data?.cuentas ?? []
  const cuenta = f.cuenta || (cuentas.length === 1 ? String(cuentas[0].id) : '')
  // Se manda el total que la persona ve: si cambió, el servidor no deposita.
  const cuerpo = { fecha: f.fecha, cuenta: Number(cuenta) || null, total: cts.total, ...(f.medio ? { medio_pago: Number(f.medio) } : {}), referencia: f.referencia.trim() }
  const llave = useClaveIdempotente(cuerpo)
  const depositar = useDepositarCts(cts.id, { exito: 'CTS depositada: el dinero salió de la caja.', alExito: () => onCerrar() })

  const enviar = (evento) => {
    evento.preventDefault()
    if (depositar.isPending) return
    const e = {}
    if (!f.fecha) e.fecha = 'Indique la fecha del depósito.'
    else if (f.fecha > hoyIso()) e.fecha = 'No puede ser futura.'
    if (!cuenta) e.cuenta = 'Elija de qué caja o cuenta sale el dinero.'
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return
    depositar.mutate(
      { datos: cuerpo, llave },
      {
        onError: (error) => {
          const delServidor = erroresDeCampo(error)
          setErrores(delServidor)
          setGeneral(Object.keys(delServidor).length > 0 && codigoDeError(error) === 'validacion' ? 'Revise los datos marcados.' : mensajeDeError(error))
        },
      },
    )
  }

  return (
    <Modal titulo="Depositar la CTS" subtitulo={`${cts.periodo_nombre} ${cts.anio} · ${soles(cts.total)}`} onCerrar={onCerrar} ancho={620}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={depositar.isPending} className="rh-opciones">
          <p className="rh-aviso">Se registra un egreso por trabajador desde la caja o cuenta elegida. El depósito en el banco de cada trabajador se hace aparte; aquí queda el registro.</p>
          <div className="rh-fila-campos">
            <Campo etiqueta="Fecha del depósito" requerido error={errores.fecha}>
              {(p) => <input {...p} type="date" max={hoyIso()} value={f.fecha} onChange={(e) => setF({ ...f, fecha: e.target.value })} />}
            </Campo>
            <Campo etiqueta="Sale de" tipo="select" requerido error={errores.cuenta}>
              {(p) => (
                <select {...p} value={cuenta} onChange={(e) => setF({ ...f, cuenta: e.target.value })}>
                  <option value="">Elija…</option>
                  {cuentas.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.nombre}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Método de pago" tipo="select" error={errores.medio_pago}>
              {(p) => (
                <select {...p} value={f.medio} onChange={(e) => setF({ ...f, medio: e.target.value })}>
                  <option value="">Sin indicar</option>
                  {(opciones.data?.medios_pago ?? []).map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.nombre}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="N° de operación" error={errores.referencia} contador={{ actual: f.referencia.length, max: 60 }}>
              {(p) => <input {...p} maxLength={60} value={f.referencia} onChange={(e) => setF({ ...f, referencia: e.target.value })} />}
            </Campo>
          </div>
        </fieldset>
        {(general || errores.total) && (
          <p role="alert" className="campo-error">
            {general || errores.total}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={depositar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={depositar.isPending}>
            {depositar.isPending ? 'Depositando…' : 'Depositar'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

/** Anula el depósito (con motivo) o descarta el cálculo en revisión. */
export function AccionCtsModal({ cts, tipo, onCerrar, onListo }) {
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')
  const anular = useAccionCts(cts.id, 'anular-deposito', { exito: 'Depósito anulado: el dinero volvió a la caja.', alExito: () => onCerrar() })
  const descartar = useDescartarCts(cts.id, { exito: 'Cálculo descartado.', alExito: () => onListo?.() })
  const enviando = anular.isPending || descartar.isPending

  const confirmar = (evento) => {
    evento.preventDefault()
    if (enviando) return
    setError('')
    const alError = { onError: (e) => setError(mensajeDeError(e)) }
    if (tipo === 'descartar') return descartar.mutate(undefined, alError)
    if (!motivo.trim()) return setError('Indique el motivo de la anulación.')
    return anular.mutate({ motivo: motivo.trim() }, alError)
  }

  return (
    <Modal titulo={tipo === 'descartar' ? 'Descartar el cálculo de CTS' : 'Anular el depósito de CTS'} subtitulo={`${cts.periodo_nombre} ${cts.anio}`} onCerrar={onCerrar} ancho={480}>
      <form onSubmit={confirmar} noValidate className="rh-opciones">
        {tipo === 'descartar' ? (
          <p>Se elimina este cálculo. Puedes volver a calcularlo cuando quieras.</p>
        ) : (
          <>
            <p className="rh-aviso">Los egresos de la caja se anulan (el dinero vuelve) y el cálculo queda otra vez en revisión.</p>
            <fieldset disabled={enviando} className="rh-opciones">
              <Campo etiqueta="Motivo de la anulación" requerido error={error} contador={{ actual: motivo.length, max: 250 }}>
                {(p) => <input {...p} maxLength={250} value={motivo} onChange={(e) => setMotivo(e.target.value)} />}
              </Campo>
            </fieldset>
          </>
        )}
        {error && tipo === 'descartar' && (
          <p role="alert" className="campo-error">
            {error}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={enviando}>
            Cancelar
          </button>
          <button type="submit" className={tipo === 'descartar' ? 'peligro' : 'primario'} disabled={enviando}>
            {enviando ? 'Procesando…' : tipo === 'descartar' ? 'Descartar' : 'Confirmar anulación'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
