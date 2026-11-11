import { useState } from 'react'
import { codigoDeError, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { useAnularPago, useOpcionesPago, usePagarPlanilla } from '../hooks/usePlanilla'
import { fechaCorta, mesAnio, soles } from '../rrhh'
import '../rrhh.css'

const hoy = () => new Date().toLocaleDateString('en-CA') // AAAA-MM-DD en la hora local

/** Paga el neto de los trabajadores que todavía no cobraron: sale de una caja o cuenta en soles. */
export function PagarModal({ planilla, onCerrar }) {
  const opciones = useOpcionesPago(planilla.id)
  const pendientes = planilla.trabajadores.filter((t) => !t.pago && Number(t.neto) > 0)
  const [elegidos, setElegidos] = useState(() => new Set(pendientes.map((t) => t.id)))
  const [f, setF] = useState({ fecha: hoy(), cuenta: '', medio: '', referencia: '' })
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')
  const cuentas = opciones.data?.cuentas ?? []
  const cuenta = f.cuenta || (cuentas.length === 1 ? String(cuentas[0].id) : '')
  const total = pendientes.filter((t) => elegidos.has(t.id)).reduce((suma, t) => suma + Number(t.neto), 0)

  const cuerpo = { detalles: [...elegidos].sort((a, b) => a - b), fecha: f.fecha, cuenta: Number(cuenta) || null, ...(f.medio ? { medio_pago: Number(f.medio) } : {}), referencia: f.referencia.trim() }
  const llave = useClaveIdempotente(cuerpo)
  const pagar = usePagarPlanilla(planilla.id, { exito: 'Sueldos pagados: el dinero salió de la caja.', alExito: () => onCerrar() })

  const alternar = (id) =>
    setElegidos((previo) => {
      const nuevo = new Set(previo)
      if (nuevo.has(id)) nuevo.delete(id)
      else nuevo.add(id)
      return nuevo
    })

  const enviar = (evento) => {
    evento.preventDefault()
    if (pagar.isPending) return
    const e = {}
    if (elegidos.size === 0) e.detalles = 'Elija a quién se le paga.'
    if (!f.fecha) e.fecha = 'Indique la fecha de pago.'
    else if (f.fecha > hoy()) e.fecha = 'No puede ser futura.'
    if (!cuenta) e.cuenta = 'Elija de qué caja o cuenta sale el dinero.'
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return
    pagar.mutate(
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
    <Modal titulo={`Pagar sueldos de ${mesAnio(planilla.periodo)}`} subtitulo="Se paga el neto de cada trabajador y sale de una caja o cuenta en soles." onCerrar={onCerrar} ancho={720}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={pagar.isPending} className="rh-opciones">
          <div className="marco-tabla">
            <table className="tabla-datos">
              <caption className="sr-only">Trabajadores por pagar</caption>
              <thead>
                <tr>
                  <th>
                    <input
                      type="checkbox"
                      aria-label="Elegir a todos"
                      checked={elegidos.size === pendientes.length && pendientes.length > 0}
                      onChange={(e) => setElegidos(e.target.checked ? new Set(pendientes.map((t) => t.id)) : new Set())}
                    />
                  </th>
                  <th>Trabajador</th>
                  <th className="derecha">Neto</th>
                </tr>
              </thead>
              <tbody>
                {pendientes.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <input type="checkbox" aria-label={`Pagar a ${t.nombre_completo}`} checked={elegidos.has(t.id)} onChange={() => alternar(t.id)} />
                    </td>
                    <td>{t.nombre_completo}</td>
                    <td className="derecha">{soles(t.neto)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {errores.detalles && (
            <p role="alert" className="campo-error">
              {errores.detalles}
            </p>
          )}
          <p style={{ margin: 0, textAlign: 'right' }}>
            Total a pagar: <strong>{soles(total)}</strong>
          </p>
          <div className="rh-fila-campos">
            <Campo etiqueta="Fecha de pago" requerido error={errores.fecha}>
              {(p) => <input {...p} type="date" max={hoy()} value={f.fecha} onChange={(e) => setF({ ...f, fecha: e.target.value })} />}
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
        {general && (
          <p role="alert" className="campo-error">
            {general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={pagar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={pagar.isPending || pendientes.length === 0}>
            {pagar.isPending ? 'Pagando…' : 'Pagar'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

/** Anula el pago de un trabajador: el dinero vuelve a la caja y queda por pagar otra vez. */
export function AnularPagoModal({ planilla, trabajador, onCerrar }) {
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')
  const anular = useAnularPago(planilla.id, { exito: 'Pago anulado: el dinero volvió a la caja.', alExito: () => onCerrar() })

  const confirmar = (evento) => {
    evento.preventDefault()
    if (anular.isPending) return
    if (!motivo.trim()) return setError('Indique el motivo de la anulación.')
    setError('')
    return anular.mutate({ pago: trabajador.pago.id, motivo: motivo.trim() }, { onError: (e) => setError(mensajeDeError(e)) })
  }

  return (
    <Modal titulo="Anular pago de sueldo" subtitulo={`${trabajador.nombre_completo} · pagado el ${fechaCorta(trabajador.pago.fecha)}`} onCerrar={onCerrar} ancho={480}>
      <form onSubmit={confirmar} noValidate className="rh-opciones">
        <p className="rh-aviso">El egreso de la caja se anula (el dinero vuelve) y el trabajador queda por pagar.</p>
        <fieldset disabled={anular.isPending} className="rh-opciones">
          <Campo etiqueta="Motivo de la anulación" requerido error={error} contador={{ actual: motivo.length, max: 250 }}>
            {(p) => <input {...p} maxLength={250} value={motivo} onChange={(e) => setMotivo(e.target.value)} />}
          </Campo>
        </fieldset>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={anular.isPending}>
            Volver
          </button>
          <button type="submit" className="primario" disabled={anular.isPending}>
            {anular.isPending ? 'Anulando…' : 'Confirmar anulación'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
