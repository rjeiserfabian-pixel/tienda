import Link from 'next/link'
import '@/app/listado.css'
import BotonFiltros from './BotonFiltros'
import ChipsFiltros from './ChipsFiltros'
import FiltrosPanel from './FiltrosPanel'
import { textoCantidad } from './listado-util'
import Migas from './Migas'
import Ordenar from './Ordenar'
import Paginacion from './Paginacion'
import ProductoTarjeta from './ProductoTarjeta'

const PRIORITARIAS = 4

/** Cuántos filtros hay aplicados que la persona puede quitar (sin contar los que definen la página). */
export function contarFiltrosActivos(filtros, { marcaFija = false, esBusqueda = false } = {}) {
  let n = 0
  if (!marcaFija) n += filtros.marca.length
  if (filtros.precio_min || filtros.precio_max) n += 1
  if (filtros.disponible) n += 1
  if (!esBusqueda) {
    if (filtros.nuevo) n += 1
    if (filtros.destacado) n += 1
    if (filtros.q) n += 1
  }
  for (const valores of Object.values(filtros.esp)) n += valores.length
  return n
}

/** Qué decir cuando no hay productos que mostrar. */
function EstadoVacio({ conFiltros, rutaLimpia, menu, esBusqueda, texto }) {
  const categorias = (menu?.familias ?? []).flatMap((f) => f.categorias).slice(0, 8)
  return (
    <div className="estado-vacio lis-vacio">
      <h2>{conFiltros ? 'No encontramos productos con esos filtros' : esBusqueda ? `Sin resultados para «${texto}»` : 'Aún no hay productos aquí'}</h2>
      <p>
        {conFiltros
          ? 'Prueba quitando alguno de los filtros para ver más opciones.'
          : 'Revisa que esté bien escrito o prueba con una palabra más corta. También puedes explorar nuestras categorías.'}
      </p>
      {conFiltros && (
        <Link href={rutaLimpia} className="boton" scroll={false}>
          Quitar filtros
        </Link>
      )}
      {categorias.length > 0 && (
        <ul className="lis-sugerencias" aria-label="Categorías sugeridas">
          {categorias.map((c) => (
            <li key={c.slug}>
              <Link href={`/categoria/${c.slug}`} className="lis-pildora">
                {c.nombre}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * Página de listado común a categorías, familias, marcas y búsquedas.
 * Servidor: arma la rejilla, los chips y la paginación; los filtros y el orden son componentes de
 * cliente que solo navegan (el estado vive en la dirección).
 */
export default function Listado({
  titulo,
  descripcion,
  migas,
  datos,
  filtros,
  rutaBase,
  rutaLimpia,
  menu,
  marcaFija = false,
  esBusqueda = false,
  subcategorias,
}) {
  const facetas = datos.filtros
  const activos = contarFiltrosActivos(filtros, { marcaFija, esBusqueda })
  const total = datos.count
  const desde = total === 0 ? 0 : (datos.page - 1) * datos.page_size + 1
  const hasta = Math.min(datos.page * datos.page_size, total)

  return (
    <main id="contenido" className="contenedor pagina lis">
      <Migas items={migas} />

      <header className="lis-cabecera">
        <h1 className="titulo-pagina">{titulo}</h1>
        {descripcion && <p className="subtitulo">{descripcion}</p>}
        {subcategorias?.length > 0 && (
          <ul className="lis-sugerencias" aria-label="Categorías de esta familia">
            {subcategorias.map((c) => (
              <li key={c.slug}>
                <Link href={`/categoria/${c.slug}`} className="lis-pildora">
                  {c.nombre} <small>{c.cantidad}</small>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </header>

      <div className="lis-cuerpo">
        <FiltrosPanel
          rutaBase={rutaBase}
          rutaLimpia={rutaLimpia}
          filtros={filtros}
          facetas={facetas}
          total={total}
          marcaFija={marcaFija}
          hayFiltros={activos > 0}
        />

        <section className="lis-resultados" aria-label="Resultados">
          <div className="lis-barra">
            <p className="lis-cantidad" aria-live="polite">
              <strong>{textoCantidad(total)}</strong>
              {datos.paginas > 1 && (
                <span>
                  {' '}
                  · mostrando {desde}–{hasta}
                </span>
              )}
            </p>
            <div className="lis-barra-acciones">
              <BotonFiltros activos={activos} />
              <Ordenar rutaBase={rutaBase} filtros={filtros} />
            </div>
          </div>

          <ChipsFiltros
            rutaBase={rutaBase}
            rutaLimpia={rutaLimpia}
            filtros={filtros}
            facetas={facetas}
            marcaFija={marcaFija}
            marcasConocidas={menu?.marcas}
          />

          {datos.results.length > 0 ? (
            <ul className="lis-rejilla">
              {datos.results.map((p, i) => (
                <li key={p.id}>
                  <ProductoTarjeta producto={p} prioridad={i < PRIORITARIAS} />
                </li>
              ))}
            </ul>
          ) : (
            <EstadoVacio
              conFiltros={activos > 0}
              rutaLimpia={rutaLimpia}
              menu={menu}
              esBusqueda={esBusqueda}
              texto={filtros.q}
            />
          )}

          <Paginacion rutaBase={rutaBase} filtros={filtros} pagina={datos.page} paginas={datos.paginas} />
        </section>
      </div>
    </main>
  )
}
