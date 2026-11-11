import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { dinero } from '../../compras/compras'
import { MEDIOS_AVISO } from '../servicio'

/** Registra que el cliente aprobó el presupuesto: cómo respondió. Al aprobar se reservan los repuestos. */
export default function AprobarPresupuestoModal({ orden, onCerrar }) {
  const [medio, setMedio] = useState('WHATSAPP')
  const [nota, setNota] = useState('')
  const [error, setError] = useState('')
  const p = orden.presupuesto

  const aprobar = useMutacion({
    mutationFn: (cuerpo) => api.post(`/servicio-tecnico/ordenes/${orden.id}/aprobar/`, cuerpo).then((r) => r.data),
    invalidar: [['servicio'], ['almacen']],
    exito: (r) => (r.reserva?.pendientes?.length ? `Presupuesto aprobado. Faltan ${r.reserva.pendientes.length} repuesto(s) por reservar.` : 'Presupuesto aprobado.'),
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (aprobar.isPending) return
    if (nota.trim().length < 3) return setError('Anota cómo aprobó el cliente (por ejemplo: «Aprobó por WhatsApp»).')
    setError('')
    aprobar.mutate({ medio, nota: nota.trim() }, { onError: (e) => setError(erroresDeCampo(e).nota || mensajeDeError(e)) })
  }

  return (
    <Modal titulo="Registrar la aprobación" subtitulo={`Orden ${orden.codigo} · ${orden.cliente_nombre}`} onCerrar={onCerrar} ancho={540}>
      <form onSubmit={enviar} noValidate>
        <p>
          Presupuesto {p.proforma.numero_completo}
          {p.total !== null && p.total !== undefined ? ` por ${dinero(p.total, p.proforma.moneda)}` : ''}. Al aprobarlo, la orden pasa a «Aprobado / Programado» y los repuestos se reservan en el almacén.
        </p>
        <Campo etiqueta="¿Cómo respondió el cliente?" tipo="select">
          {(c) => (
            <select {...c} value={medio} disabled={aprobar.isPending} onChange={(e) => setMedio(e.target.value)}>
              {MEDIOS_AVISO.map(([valor, texto]) => (
                <option key={valor} value={valor}>
                  {texto}
                </option>
              ))}
            </select>
          )}
        </Campo>
        <Campo etiqueta="Detalle de la aprobación" requerido error={error} contador={{ actual: nota.length, max: 500 }}>
          {(c) => <textarea {...c} rows={3} maxLength={500} placeholder="Ej. Aprobó el presupuesto por WhatsApp el 3/11 a las 4 pm." value={nota} disabled={aprobar.isPending} onChange={(e) => setNota(e.target.value)} />}
        </Campo>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={aprobar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={aprobar.isPending}>
            {aprobar.isPending ? 'Guardando…' : 'Registrar aprobación'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
