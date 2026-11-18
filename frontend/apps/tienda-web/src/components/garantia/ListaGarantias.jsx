import Link from 'next/link'
import { fechaDia } from '@/lib/format'

const TONO = { VIGENTE: 'ok', POR_VENCER: 'poco', VENCIDA: 'agotado', ANULADA: '', REEMPLAZADA: '' }
const ETIQUETA = { VIGENTE: 'Vigente', POR_VENCER: 'Por vencer', VENCIDA: 'Vencida', ANULADA: 'Anulada', REEMPLAZADA: 'Reemplazada' }

/** La garantía de cada producto comprado: hasta cuándo vale y el enlace para consultarla. */
export default function ListaGarantias({ garantias, conPedido = false }) {
  return (
    <ul className="ped-comprobantes">
      {garantias.map((g, i) => (
        <li key={`${g.enlace || g.producto}-${i}`}>
          <strong>
            {g.producto}
            {g.cantidad > 1 ? ` (${g.cantidad})` : ''}
          </strong>
          <span className="com-chico">
            {g.numero_serie ? `Serie ${g.numero_serie} · ` : ''}
            {g.meses} {g.meses === 1 ? 'mes' : 'meses'} · hasta el {fechaDia(g.hasta)}
            {g.vigente ? ` (quedan ${g.dias_restantes} ${g.dias_restantes === 1 ? 'día' : 'días'})` : ''}
            {conPedido && g.pedido ? ` · Pedido ${g.pedido}` : ''}
          </span>
          <span className={`insignia ${TONO[g.situacion] ?? ''}`}>{ETIQUETA[g.situacion] ?? g.situacion}</span>
          {g.enlace && (
            <Link href={g.enlace} className="enlace com-chico">
              Ver mi garantía
            </Link>
          )}
        </li>
      ))}
    </ul>
  )
}
