import '@/app/compra.css'
import '@/app/pedidos.css'
import PedidoDetalle from '@/components/PedidoDetalle'

export const metadata = { title: 'Mi pedido' }

export default async function Pagina({ params }) {
  const { numero } = await params
  return <PedidoDetalle numero={numero} />
}
