import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import { fechaCorta } from '../../almacen/inventario'
import { dinero, esAbono } from '../caja'

/**
 * El banco cobró o abonó algo que no estaba en el libro (comisión, ITF, intereses…): se anota como
 * un movimiento de la cuenta con la fecha del banco y la línea queda conciliada.
 */
export default function RegistrarPartidaModal({ linea, moneda, onCerrar }) {
  const abono = esAbono(linea.monto)
  const conceptos = useOpciones('/mantenimiento/conceptos-caja/', { manual: '1', tipo: abono ? 'INGRESO' : 'EGRESO' }).data ?? []
  const [concepto, setConcepto] = useState('')
  const [glosa, setGlosa] = useState(linea.descripcion ?? '')
  const [error, setError] = useState('')

  const registrar = useMutacion({
    mutationFn: (cuerpo) => api.post(`/caja/lineas-extracto/${linea.id}/registrar/`, cuerpo).then((r) => r.data),
    invalidar: [['caja']],
    exito: 'Movimiento registrado y línea conciliada.',
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (registrar.isPending) return
    if (!concepto) return setError('Elija el concepto.')
    setError('')
    registrar.mutate({ concepto: Number(concepto), ...(glosa.trim() ? { glosa: glosa.trim() } : {}) }, { onError: (e) => setError(erroresDeCampo(e).concepto || mensajeDeError(e)) })
  }

  return (
    <Modal titulo={abono ? 'Registrar el abono del banco' : 'Registrar el cargo del banco'} subtitulo={`${fechaCorta(linea.fecha)} · ${dinero(linea.monto, moneda)}${linea.referencia ? ` · Operación ${linea.referencia}` : ''}`} onCerrar={onCerrar} ancho={560}>
      <form onSubmit={enviar} noValidate>
        <p>
          El banco {abono ? 'abonó' : 'cobró'} {dinero(Math.abs(Number(linea.monto)), moneda)} que el libro no tiene. Se anotará con la fecha del banco y quedará conciliado.
        </p>
        <fieldset disabled={registrar.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
          <Campo etiqueta="Concepto" tipo="select" requerido error={error}>
            {(p) => (
              <select {...p} value={concepto} onChange={(e) => setConcepto(e.target.value)}>
                <option value="">Elija el concepto</option>
                {conceptos.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.nombre}
                  </option>
                ))}
              </select>
            )}
          </Campo>
          <Campo etiqueta="Detalle (glosa)" contador={{ actual: glosa.length, max: 250 }}>
            {(p) => <input {...p} maxLength={250} value={glosa} onChange={(e) => setGlosa(e.target.value)} />}
          </Campo>
        </fieldset>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={registrar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={registrar.isPending}>
            {registrar.isPending ? 'Registrando…' : 'Registrar y conciliar'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
