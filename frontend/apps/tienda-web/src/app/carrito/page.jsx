import CarritoVista from '@/components/CarritoVista'
import { obtenerMenu } from '@/lib/api'
import '../carrito.css'

export const metadata = {
  title: 'Mi carrito',
  robots: { index: false, follow: false },
}

export default async function PaginaCarrito() {
  // Las categorías se usan solo cuando el carrito está vacío (para seguir comprando).
  const menu = await obtenerMenu().catch(() => null)
  const categorias = (menu?.familias ?? []).flatMap((f) => f.categorias).slice(0, 8)
  return (
    <main id="contenido" className="contenedor pagina carrito-pagina">
      <CarritoVista categorias={categorias} />
    </main>
  )
}
