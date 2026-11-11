import Listado from '@/components/Listado'
import { cargarListado } from '@/components/listado-util'
import { obtenerMenu } from '@/lib/api'
import { leerFiltros } from '@/lib/filtros'

function titulo(filtros) {
  if (filtros.q) return `Resultados para «${filtros.q}»`
  if (filtros.nuevo) return 'Novedades'
  if (filtros.destacado) return 'Destacados'
  return 'Todos los productos'
}

/** Las búsquedas no se indexan: son infinitas y repiten el catálogo. */
export async function generateMetadata({ searchParams }) {
  const filtros = leerFiltros(await searchParams)
  return { title: titulo(filtros), robots: { index: false, follow: true } }
}

export default async function PaginaBuscar({ searchParams }) {
  const filtros = leerFiltros(await searchParams)
  const [datos, menu] = await Promise.all([cargarListado(filtros), obtenerMenu()])

  // `buscar` sin categoría no puede dar 404; si la API lo dijera, se muestra como sin resultados.
  const vacio = { count: 0, page: 1, page_size: 24, paginas: 1, results: [], filtros: null }

  return (
    <Listado
      titulo={titulo(filtros)}
      migas={[{ nombre: 'Inicio', href: '/' }, { nombre: 'Buscar' }]}
      datos={datos ?? vacio}
      filtros={filtros}
      rutaBase="/buscar"
      rutaLimpia={filtros.q ? `/buscar?q=${encodeURIComponent(filtros.q)}` : filtros.nuevo ? '/buscar?nuevo=1' : filtros.destacado ? '/buscar?destacado=1' : '/buscar'}
      menu={menu}
      esBusqueda
    />
  )
}
