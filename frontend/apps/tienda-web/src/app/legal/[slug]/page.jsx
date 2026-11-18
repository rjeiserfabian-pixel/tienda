import { notFound } from 'next/navigation'
import Migas from '@/components/Migas'
import { consultarOpcional, consultar } from '@/lib/api'
import '../../legal.css'

export const revalidate = 300

const cargar = (slug) => consultarOpcional(consultar, `paginas/${encodeURIComponent(slug)}/`)

export async function generateMetadata({ params }) {
  const { slug } = await params
  const p = await cargar(slug).catch(() => null)
  if (!p) return { title: 'Página no encontrada', robots: { index: false } }
  return { title: p.titulo, alternates: { canonical: `/legal/${p.slug}` } }
}

/** El texto se muestra siempre como texto (nunca como HTML): subtítulos con «# » y párrafos. */
function Contenido({ texto }) {
  return texto.split(/\n{2,}/).map((bloque, i) => {
    const lineas = bloque.split('\n')
    return (
      <div key={i}>
        {lineas.map((l, j) =>
          l.startsWith('# ') ? (
            <h2 key={j}>{l.slice(2)}</h2>
          ) : (
            <p key={j}>{l}</p>
          ),
        )}
      </div>
    )
  })
}

export default async function PaginaLegal({ params }) {
  const { slug } = await params
  const p = await cargar(slug)
  if (!p) notFound()
  return (
    <main id="contenido" className="contenedor pagina leg-pagina">
      <Migas items={[{ nombre: 'Inicio', href: '/' }, { nombre: p.titulo }]} />
      <article className="leg-texto">
        <h1 className="titulo-pagina">{p.titulo}</h1>
        <Contenido texto={p.contenido} />
        <p className="com-chico">Última actualización: {new Date(p.actualizada).toLocaleDateString('es-PE', { dateStyle: 'long' })}</p>
      </article>
    </main>
  )
}
