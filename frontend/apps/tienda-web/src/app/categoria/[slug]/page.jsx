import { notFound } from 'next/navigation'
import Listado from '@/components/Listado'
import { cargarListado, metadatosDeListado } from '@/components/listado-util'
import { obtenerMenu } from '@/lib/api'
import { leerFiltros } from '@/lib/filtros'

export async function generateMetadata({ params, searchParams }) {
  const { slug } = await params
  const filtros = leerFiltros(await searchParams)
  const datos = await cargarListado({ ...filtros, page: 1 }, { categoria: slug, page_size: 1 }).catch(() => null)
  if (!datos) return { title: 'Categoría no encontrada', robots: { index: false } }
  const nombre = datos.categoria?.nombre ?? slug
  return metadatosDeListado({
    ruta: `/categoria/${slug}`,
    titulo: nombre,
    descripcion: `Compra ${nombre} al mejor precio. Envío a domicilio y recojo en tienda.`,
    filtros,
  })
}

export default async function PaginaCategoria({ params, searchParams }) {
  const { slug } = await params
  const filtros = leerFiltros(await searchParams)
  const [datos, menu] = await Promise.all([cargarListado(filtros, { categoria: slug }), obtenerMenu()])
  if (!datos) notFound()

  const categoria = datos.categoria ?? { nombre: slug }
  const familia = categoria.familia
  const migas = [
    { nombre: 'Inicio', href: '/' },
    ...(familia?.slug ? [{ nombre: familia.nombre, href: `/familia/${familia.slug}` }] : []),
    { nombre: categoria.nombre },
  ]

  return (
    <Listado
      titulo={categoria.nombre}
      migas={migas}
      datos={datos}
      filtros={filtros}
      rutaBase={`/categoria/${slug}`}
      rutaLimpia={`/categoria/${slug}`}
      menu={menu}
    />
  )
}
