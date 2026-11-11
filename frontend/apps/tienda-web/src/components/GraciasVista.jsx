'use client'

import { useSearchParams } from 'next/navigation'
import { useRef } from 'react'
import useSesionRequerida from './cuenta/useSesionRequerida'
import PedidoDetalle from './PedidoDetalle'

/** Pantalla posterior al pago: pide el pedido por su número (que no es un dato sensible). */
export default function GraciasVista() {
  const numero = useSearchParams().get('pedido') ?? ''
  const estado = useSesionRequerida(useRef(false))
  if (!/^T-\d{3,10}$/.test(numero)) {
    return <p className="alerta error">No encontramos ese pedido. Revisa «Mis pedidos» en tu cuenta.</p>
  }
  if (estado !== 'autenticado') return <span className="esqueleto" style={{ height: 320, borderRadius: 14 }} aria-busy="true" />
  return <PedidoDetalle numero={numero} gracias />
}
