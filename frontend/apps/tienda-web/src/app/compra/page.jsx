import CompraVista from '@/components/CompraVista'
import '../compra.css'

export const metadata = {
  title: 'Terminar mi compra',
  robots: { index: false, follow: false },
}

export default function PaginaCompra() {
  return (
    <main id="contenido" className="contenedor pagina compra-pagina">
      <CompraVista />
    </main>
  )
}
