import { notFound } from 'next/navigation'
import Listado from '@/components/Listado'
import { cargarListado, metadatosDeListado } from '@/components/listado-util'
import { obtenerMenu } from '@/lib/api'
import { leerFiltros } from '@/lib/filtros'

/** La marca de la dirección manda: se ignora cualquier `marca` que venga en la consulta. */
const sinMarca = (filtros) => ({ ...filtros, marca: [] })

export async function generateMetadata({ params, searchParams }) {
  const { slug } = await params
  const filtros = sinMarca(leerFiltros(await searchParams))
  const menu = await obtenerMenu().catch(() => null)
  const marca = menu?.marcas?.find((m) => m.slug === slug)
  if (!marca) return { title: 'Marca no encontrada', robots: { index: false } }
  return metadatosDeListado({
    ruta: `/marca/${slug}`,
    titulo: `Productos ${marca.nombre}`,
    descripcion: `Productos ${marca.nombre} con precios en soles, envío a domicilio y recojo en tienda.`,
    filtros,
  })
}

export default async function PaginaMarca({ params, searchParams }) {
  const { slug } = await params
  const filtros = sinMarca(leerFiltros(await searchParams))
  const [datos, menu] = await Promise.all([cargarListado({ ...filtros, marca: [slug] }), obtenerMenu()])
  const marca = menu.marcas.find((m) => m.slug === slug)
  if (!datos || !marca) notFound()

  return (
    <Listado
      titulo={marca.nombre}
      migas={[{ nombre: 'Inicio', href: '/' }, { nombre: 'Marcas' }, { nombre: marca.nombre }]}
      datos={datos}
      filtros={filtros}
      rutaBase={`/marca/${slug}`}
      rutaLimpia={`/marca/${slug}`}
      menu={menu}
      marcaFija
    />
  )
}
