import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { hoyIso, paraServidor } from '../../almacen/inventario'
import { ACCIONES, ayudaDeAccion } from '../cheques'
import { dinero } from '../caja'

const URL_DE = { depositar: 'depositar', cobrar: 'cobrar', rechazar: 'rechazar', anular: 'anular', deshacer: 'deshacer-cobro' }
const EXITO = {
  depositar: 'Cheque depositado.',
  cobrar: 'Cheque cobrado.',
  rechazar: 'Cheque rechazado.',
  anular: 'Cheque anulado.',
  deshacer: 'Cobro deshecho.',
}

/**
 * Una acción sobre un cheque, con su explicación y confirmación: depositar, cobrar, rechazar,
 * anular o deshacer el cobro. Solo pide los datos que esa acción necesita.
 */
export default function AccionChequeModal({ cheque, accion, cuentas, onCerrar }) {
  const { empresaActivaId } = useEmpresas()
  const recibido = cheque.tipo === 'RECIBIDO'
  const pideBanco = recibido && (accion === 'depositar' || accion === 'cobrar')
  const pideFecha = accion === 'depositar' || accion === 'cobrar'
  const pideMotivo = ['rechazar', 'anular', 'deshacer'].includes(accion)
  const pideCartera = recibido && accion === 'cobrar'

  const bancos = (cuentas ?? []).filter((c) => c.estado === 'ACTIVO' && c.tipo === 'BANCO' && c.moneda === cheque.moneda)
  const deCheques = useQuery({
    queryKey: ['caja', 'cheques', 'cuentas', empresaActivaId],
    queryFn: ({ signal }) => api.get('/caja/cheques/cuentas/', { params: { empresa: empresaActivaId }, signal }).then((r) => r.data),
    enabled: pideCartera && Boolean(empresaActivaId),
  })
  const otras = (cuentas ?? []).filter((c) => c.estado === 'ACTIVO' && c.moneda === cheque.moneda && c.tipo !== 'CAJA')
  const sugeridas = (deCheques.data ?? []).filter((c) => c.moneda === cheque.moneda)

  const [f, setF] = useState({
    cuenta: cheque.cuenta ? String(cheque.cuenta) : '',
    cartera: cheque.cuenta_cartera ? String(cheque.cuenta_cartera) : '',
    fecha: hoyIso(),
    motivo: '',
    comision: '',
  })
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')
  const poner = (campo, valor) => setF((previo) => ({ ...previo, [campo]: valor }))
  const carteraElegida = f.cartera || (sugeridas.length === 1 ? String(sugeridas[0].id) : '')

  const ejecutar = useMutacion({
    mutationFn: (cuerpo) => api.post(`/caja/cheques/${cheque.id}/${URL_DE[accion]}/`, cuerpo, { timeout: 30_000 }).then((r) => r.data),
    invalidar: [['caja']],
    exito: EXITO[accion],
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (ejecutar.isPending) return
    const e = {}
    if (pideBanco && !f.cuenta) e.cuenta = 'Elija el banco.'
    if (pideCartera && !carteraElegida) e.cartera = 'Elija la cuenta de cheques de donde sale el dinero.'
    if (pideFecha && !f.fecha) e.fecha = 'Indique la fecha.'
    else if (pideFecha && (f.fecha > hoyIso() || f.fecha < cheque.fecha_emision)) e.fecha = 'Debe estar entre la emisión del cheque y hoy.'
    if (pideMotivo && f.motivo.trim().length < 3) e.motivo = 'Escriba el motivo (mínimo 3 letras).'
    const comision = paraServidor(f.comision)
    if (accion === 'rechazar' && comision && !/^\d+(\.\d{1,2})?$/.test(comision)) e.comision = 'Un monto con hasta 2 decimales.'
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return

    let cuerpo = {}
    if (accion === 'depositar') cuerpo = { cuenta: Number(f.cuenta), fecha: f.fecha }
    else if (accion === 'cobrar') cuerpo = { fecha: f.fecha, ...(pideBanco ? { cuenta: Number(f.cuenta), cuenta_cartera: Number(carteraElegida) } : {}) }
    else if (accion === 'rechazar') cuerpo = { motivo: f.motivo.trim(), ...(comision ? { comision } : {}) }
    else cuerpo = { motivo: f.motivo.trim() }
    ejecutar.mutate(cuerpo, {
      onError: (error) => {
        const campos = erroresDeCampo(error)
        const delServidor = {}
        for (const [origen, destino] of [['cuenta', 'cuenta'], ['cuenta_cartera', 'cartera'], ['fecha', 'fecha'], ['motivo', 'motivo'], ['comision', 'comision']]) if (campos[origen]) delServidor[destino] = campos[origen]
        setErrores(delServidor)
        setGeneral(Object.keys(delServidor).length ? 'Revise los datos marcados.' : mensajeDeError(error))
      },
    })
  }

  const info = ACCIONES[accion]
  const etiquetaBoton = accion === 'cobrar' && !recibido ? 'Marcar cobrado' : info.boton

  return (
    <Modal titulo={info.titulo} subtitulo={`Cheque ${cheque.numero} · ${cheque.banco} · ${dinero(cheque.importe, cheque.moneda)}`} onCerrar={onCerrar} ancho={560}>
      <form onSubmit={enviar} noValidate>
        <p>{ayudaDeAccion(accion, cheque)}</p>
        <fieldset disabled={ejecutar.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
          {pideBanco && (
            <Campo etiqueta={accion === 'depositar' ? 'Banco donde se deposita' : 'Banco donde se cobró'} tipo="select" requerido error={errores.cuenta}>
              {(p) => (
                <select {...p} value={f.cuenta} onChange={(ev) => poner('cuenta', ev.target.value)}>
                  <option value="">Elija la cuenta del banco</option>
                  {bancos.map((c) => (
                    <option key={c.cuenta} value={c.cuenta}>
                      {c.nombre}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
          )}
          {pideCartera && (
            <Campo etiqueta="Cuenta de cheques (de donde sale el dinero)" tipo="select" requerido error={errores.cartera} ayuda={sugeridas.length === 0 ? 'No hay una cuenta de cobro «Cheque» configurada en Ventas: elija la cuenta donde se anotó el cobro.' : undefined}>
              {(p) => (
                <select {...p} value={carteraElegida} onChange={(ev) => poner('cartera', ev.target.value)}>
                  <option value="">Elija la cuenta</option>
                  {sugeridas.length > 0 && (
                    <optgroup label="Configuradas en Ventas">
                      {sugeridas.map((c) => (
                        <option key={`s${c.id}`} value={c.id}>
                          {c.nombre}
                        </option>
                      ))}
                    </optgroup>
                  )}
                  <optgroup label="Otras cuentas de la empresa">
                    {otras
                      .filter((c) => !sugeridas.some((s) => s.id === c.cuenta))
                      .map((c) => (
                        <option key={c.cuenta} value={c.cuenta}>
                          {c.nombre}
                        </option>
                      ))}
                  </optgroup>
                </select>
              )}
            </Campo>
          )}
          {pideFecha && (
            <Campo etiqueta="Fecha" icono="calendario" requerido error={errores.fecha}>
              {(p) => <input {...p} type="date" min={cheque.fecha_emision} max={hoyIso()} value={f.fecha} onChange={(ev) => poner('fecha', ev.target.value)} />}
            </Campo>
          )}
          {accion === 'rechazar' && recibido && (
            <Campo
              etiqueta={`Comisión del banco (${cheque.moneda === 'USD' ? 'US$' : 'S/'})`}
              error={errores.comision}
              ayuda={cheque.cuenta ? 'Opcional: sale como egreso del banco donde se depositó.' : 'Para anotar la comisión, el cheque debe estar depositado en un banco.'}
            >
              {(p) => <input {...p} inputMode="decimal" placeholder="0.00" disabled={!cheque.cuenta} value={f.comision} onChange={(ev) => poner('comision', ev.target.value)} />}
            </Campo>
          )}
          {pideMotivo && (
            <Campo etiqueta="Motivo" requerido error={errores.motivo} contador={{ actual: f.motivo.length, max: 250 }}>
              {(p) => <textarea {...p} rows={3} maxLength={250} value={f.motivo} placeholder={accion === 'rechazar' ? 'Ej. Sin fondos' : accion === 'anular' ? 'Ej. Se devolvió al cliente' : 'Ej. Se marcó por error'} onChange={(ev) => poner('motivo', ev.target.value)} />}
            </Campo>
          )}
        </fieldset>
        {general && (
          <p role="alert" className="campo-error">
            {general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={ejecutar.isPending}>
            Cancelar
          </button>
          <button type="submit" className={accion === 'anular' || accion === 'rechazar' ? 'peligro' : 'primario'} disabled={ejecutar.isPending}>
            {ejecutar.isPending ? 'Guardando…' : etiquetaBoton}
          </button>
        </div>
      </form>
    </Modal>
  )
}
