import LibroReclamaciones from '@/components/LibroReclamaciones'
import Migas from '@/components/Migas'
import { consultar } from '@/lib/api'
import '../servicio-tecnico.css'
import '../legal.css'

export const revalidate = 300
export const metadata = {
  title: 'Libro de Reclamaciones',
  description: 'Presenta un reclamo o una queja. Te respondemos en un máximo de 15 días hábiles.',
  alternates: { canonical: '/libro-de-reclamaciones' },
}

export default async function PaginaLibro() {
  const libro = await consultar('libro-de-reclamaciones/')
  return (
    <main id="contenido" className="contenedor pagina lib-pagina">
      <Migas items={[{ nombre: 'Inicio', href: '/' }, { nombre: 'Libro de Reclamaciones' }]} />
      <LibroReclamaciones libro={libro} />
    </main>
  )
}
