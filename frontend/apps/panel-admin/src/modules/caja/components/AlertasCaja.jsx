import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../../../core/api/client'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'

/** Lo que conviene mirar hoy: saldos bajos o negativos, sesiones largas, extractos sin cerrar. Si no hay nada, no se muestra. */
export default function AlertasCaja() {
  const navegar = useNavigate()
  const { empresaActivaId } = useEmpresas()
  const consulta = useQuery({
    queryKey: ['caja', 'alertas', empresaActivaId],
    queryFn: ({ signal }) => api.get('/caja/alertas/', { params: { empresa: empresaActivaId }, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId),
    staleTime: 30_000,
  })
  const avisos = consulta.data ?? []
  if (avisos.length === 0) return null
  return (
    <section aria-label="Avisos de caja">
      <ul className="caja-alertas">
        {avisos.map((a) => (
          <li key={`${a.codigo}-${a.titulo}`} data-nivel={a.nivel}>
            <div>
              <strong>{a.titulo}</strong>
              <span className="celda-suave">{a.detalle}</span>
            </div>
            <button type="button" className="boton-cabecera" onClick={() => navegar(a.enlace)}>
              Revisar
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
