import BajaPromociones from '@/components/cuenta/BajaPromociones'

export const metadata = { title: 'Darme de baja de las ofertas', robots: { index: false, follow: false } }

export default function Pagina() {
  return (
    <main id="contenido">
      <BajaPromociones />
    </main>
  )
}
