import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'

/** Una fila: el técnico y su porcentaje, que se guarda con el botón. */
function Fila({ empresa, tecnico }) {
  const [valor, setValor] = useState(String(Number(tecnico.porcentaje)))
  const [error, setError] = useState('')
  const guardar = useMutacion({
    mutationFn: (porcentaje) => api.put(`/servicio-tecnico/comisiones/${tecnico.id}/`, { porcentaje }, { params: { empresa } }).then((r) => r.data),
    invalidar: [['servicio']],
    exito: `Comisión de ${tecnico.nombre} guardada.`,
    avisarError: false,
  })
  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending) return
    const numero = Number(String(valor).replace(',', '.'))
    if (!Number.isFinite(numero) || numero < 0 || numero > 100) return setError('Use un porcentaje de 0 a 100.')
    setError('')
    guardar.mutate(numero.toFixed(2), { onError: (e) => setError(mensajeDeError(e)) })
  }
  return (
    <li>
      <form onSubmit={enviar} noValidate className="servicio-comision">
        <strong>{tecnico.nombre}</strong>
        <input inputMode="decimal" aria-label={`Porcentaje de ${tecnico.nombre}`} value={valor} disabled={guardar.isPending} onChange={(e) => setValor(e.target.value)} />
        <span>%</span>
        <button type="submit" className="boton-cabecera" disabled={guardar.isPending}>
          {guardar.isPending ? 'Guardando…' : 'Guardar'}
        </button>
        {error && (
          <span role="alert" className="campo-error">
            {error}
          </span>
        )}
      </form>
    </li>
  )
}

/** El porcentaje de comisión de cada técnico sobre la mano de obra cobrada. Vale para las entregas desde ahora. */
export default function ComisionesModal({ empresa, onCerrar }) {
  const consulta = useQuery({
    queryKey: ['servicio', 'comisiones', empresa],
    queryFn: ({ signal }) => api.get('/servicio-tecnico/comisiones/', { params: { empresa }, signal }).then((r) => r.data),
  })
  const tecnicos = consulta.data?.tecnicos ?? []
  return (
    <Modal titulo="Comisiones de los técnicos" subtitulo="Porcentaje sobre la mano de obra cobrada, sin IGV" onCerrar={onCerrar} ancho={560}>
      <p className="celda-suave">El porcentaje que pongas se aplica a las órdenes que se entreguen desde ahora; las ya entregadas conservan el que tenían ese día.</p>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        {tecnicos.length === 0 ? (
          <p className="estado-vacio">No hay personal del área técnica en esta empresa.</p>
        ) : (
          <ul className="servicio-comisiones">
            {tecnicos.map((t) => (
              <Fila key={`${t.id}-${t.porcentaje}`} empresa={empresa} tecnico={t} />
            ))}
          </ul>
        )}
      </EstadoConsulta>
      <div className="modal-pie">
        <button type="button" className="primario" onClick={onCerrar}>
          Listo
        </button>
      </div>
    </Modal>
  )
}
