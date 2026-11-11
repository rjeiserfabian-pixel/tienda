import { useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useConfiguracionServicio } from '../hooks/useConfiguracionServicio'

const VACIO = []

/** Asigna o cambia el técnico de la orden (también a uno sin usuario: sirve para sus reportes). */
export default function AsignarTecnicoModal({ orden, onCerrar }) {
  const [tecnico, setTecnico] = useState(orden.tecnico ? String(orden.tecnico) : '')
  const [error, setError] = useState('')
  const consulta = useConfiguracionServicio(orden.empresa)
  const tecnicos = consulta.data?.tecnicos ?? VACIO

  const asignar = useMutacion({
    mutationFn: (cuerpo) => api.post(`/servicio-tecnico/ordenes/${orden.id}/asignar/`, cuerpo).then((r) => r.data),
    invalidar: [['servicio']],
    exito: 'Técnico actualizado.',
    alExito: onCerrar,
    avisarError: false,
  })
  const enviar = (evento) => {
    evento.preventDefault()
    if (asignar.isPending) return
    setError('')
    asignar.mutate({ tecnico: tecnico ? Number(tecnico) : null }, { onError: (e) => setError(mensajeDeError(e)) })
  }
  const ayuda = consulta.isLoading ? 'Cargando técnicos…' : tecnicos.length === 0 ? 'No hay personal del área técnica en esta empresa.' : 'Si el técnico tiene usuario, verá la orden en «Mis órdenes».'

  return (
    <Modal titulo="Asignar técnico" subtitulo={`Orden ${orden.codigo} · ${orden.equipo_descripcion}`} onCerrar={onCerrar} ancho={500}>
      <form onSubmit={enviar} noValidate>
        <Campo etiqueta="Técnico" tipo="select" error={error} ayuda={ayuda}>
          {(p) => (
            <select {...p} value={tecnico} disabled={asignar.isPending} onChange={(e) => setTecnico(e.target.value)}>
              <option value="">Sin asignar</option>
              {tecnicos.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.nombre}
                  {t.tiene_usuario ? '' : ' (sin usuario)'}
                </option>
              ))}
            </select>
          )}
        </Campo>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={asignar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={asignar.isPending}>
            {asignar.isPending ? 'Guardando…' : 'Guardar'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
