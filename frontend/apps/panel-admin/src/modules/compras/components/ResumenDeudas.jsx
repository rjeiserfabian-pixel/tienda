import { useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'
import { dinero } from '../compras'

/** Totales de lo que se debe, por moneda: todo, lo vencido y lo que vence en la próxima semana. */
export default function ResumenDeudas({ empresaId }) {
  const consulta = useQuery({
    queryKey: ['compras', 'por-pagar-resumen', empresaId],
    queryFn: ({ signal }) => api.get('/compras/por-pagar/resumen/', { params: { empresa: empresaId }, signal }).then((r) => r.data),
    enabled: Boolean(empresaId),
  })
  if (consulta.isLoading) return <p aria-busy="true" className="celda-suave">Calculando lo que se debe…</p>
  if (consulta.isError || !consulta.data) return null
  if (consulta.data.length === 0) return <p className="celda-suave">No hay deudas pendientes con proveedores.</p>
  return (
    <div className="cxp-resumen">
      {consulta.data.map((m) => (
        <dl className="cxp-tarjetas" key={m.moneda} aria-label={`Deuda en ${m.moneda === 'USD' ? 'dólares' : 'soles'}`}>
          <div>
            <dt>Total por pagar{consulta.data.length > 1 ? ` (${m.moneda === 'USD' ? 'dólares' : 'soles'})` : ''}</dt>
            <dd>{dinero(m.saldo, m.moneda)}</dd>
            <small>{m.compras} {m.compras === 1 ? 'compra' : 'compras'}</small>
          </div>
          <div data-tono={Number(m.vencido) > 0 ? 'rojo' : undefined}>
            <dt>Vencido</dt>
            <dd>{dinero(m.vencido, m.moneda)}</dd>
            <small>Ya debió pagarse</small>
          </div>
          <div data-tono={Number(m.por_vencer_7_dias) > 0 ? 'ambar' : undefined}>
            <dt>Vence en 7 días</dt>
            <dd>{dinero(m.por_vencer_7_dias, m.moneda)}</dd>
            <small>Para esta semana</small>
          </div>
        </dl>
      ))}
    </div>
  )
}
