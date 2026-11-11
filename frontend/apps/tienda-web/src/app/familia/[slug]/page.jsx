import { notFound } from 'next/navigation'
import Listado from '@/components/Listado'
import { cargarListado, metadatosDeListado } from '@/components/listado-util'
import { obtenerMenu } from '@/lib/api'
import { leerFiltros } from '@/lib/filtros'

export async function generateMetadata({ params, searchParams }) {
  const { slug } = await params
  const filtros = leerFiltros(await searchParams)
  const menu = await obtenerMenu().catch(() => null)
  const familia = menu?.familias?.find((f) => f.slug === slug)
  if (!familia) return { title: 'Familia no encontrada', robots: { index: false } }
  return metadatosDeListado({
    ruta: `/familia/${slug}`,
    titulo: familia.nombre,
    descripcion: `Todo en ${familia.nombre}: precios en soles, envío a domicilio y recojo en tienda.`,
    filtros,
  })
}

export default async function PaginaFamilia({ params, searchParams }) {
  const { slug } = await params
  const filtros = leerFiltros(await searchParams)
  const [datos, menu] = await Promise.all([cargarListado(filtros, { familia: slug }), obtenerMenu()])
  const familia = menu.familias.find((f) => f.slug === slug)
  if (!datos || !familia) notFound()

  return (
    <Listado
      titulo={familia.nombre}
      migas={[{ nombre: 'Inicio', href: '/' }, { nombre: familia.nombre }]}
      datos={datos}
      filtros={filtros}
      rutaBase={`/familia/${slug}`}
      rutaLimpia={`/familia/${slug}`}
      menu={menu}
      subcategorias={familia.categorias}
    />
  )
}
