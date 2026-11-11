import '@/app/compra.css'
import '@/app/pedidos.css'
import ListaPedidos from '@/components/cuenta/ListaPedidos'

export const metadata = { title: 'Mis pedidos' }

export default function Pagina() {
  return (
    <>
      <h1>Mis pedidos</h1>
      <ListaPedidos />
    </>
  )
}
