import Listado from '@/components/Listado'
import { cargarListado, metadatosDeListado } from '@/components/listado-util'
import { obtenerMenu } from '@/lib/api'
import { leerFiltros } from '@/lib/filtros'

/** En «Ofertas» se ordena por mayor descuento mientras la persona no elija otra cosa. */
const conOrden = (filtros) => ({ ...filtros, orden: filtros.orden === 'relevancia' ? 'descuento' : filtros.orden })

export async function generateMetadata({ searchParams }) {
  const filtros = conOrden(leerFiltros(await searchParams))
  return metadatosDeListado({
    ruta: '/ofertas',
    titulo: 'Ofertas',
    descripcion: 'Productos con precio especial por tiempo limitado, con envío a domicilio o recojo en tienda.',
    filtros: { ...filtros, orden: 'relevancia' },
  })
}

export default async function PaginaOfertas({ searchParams }) {
  const filtros = conOrden(leerFiltros(await searchParams))
  const [datos, menu] = await Promise.all([cargarListado(filtros, { oferta: '1' }), obtenerMenu()])
  const vacio = { count: 0, page: 1, page_size: 24, paginas: 1, results: [], filtros: null }

  return (
    <Listado
      titulo="Ofertas"
      descripcion="Precios especiales por tiempo limitado. Cuando termina la oferta, el precio vuelve al normal."
      migas={[{ nombre: 'Inicio', href: '/' }, { nombre: 'Ofertas' }]}
      datos={datos ?? vacio}
      filtros={filtros}
      rutaBase="/ofertas"
      rutaLimpia="/ofertas"
      menu={menu}
    />
  )
}
