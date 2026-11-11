import Link from 'next/link'
import { enlaceConFiltros } from '@/lib/filtros'
import Icono from './Icono'
import { rangoDePaginas } from './listado-util'

/** Paginación con enlaces reales (funciona sin JavaScript y los buscadores la recorren). */
export default function Paginacion({ rutaBase, filtros, pagina, paginas }) {
  if (paginas <= 1) return null
  const href = (p) => enlaceConFiltros(rutaBase, filtros, { page: p })
  return (
    <nav className="lis-paginas" aria-label="Paginación de resultados">
      {pagina > 1 ? (
        <Link href={href(pagina - 1)} rel="prev" className="lis-pag lis-pag-flecha" aria-label="Página anterior">
          <Icono nombre="izquierda" tam={18} /> <span>Anterior</span>
        </Link>
      ) : (
        <span className="lis-pag lis-pag-flecha inactiva" aria-hidden="true">
          <Icono nombre="izquierda" tam={18} /> <span>Anterior</span>
        </span>
      )}
      <ol className="lis-pag-numeros">
        {rangoDePaginas(pagina, paginas).map((p, i) =>
          p === null ? (
            <li key={`puntos-${i}`} className="lis-pag-puntos" aria-hidden="true">
              …
            </li>
          ) : (
            <li key={p}>
              {p === pagina ? (
                <span className="lis-pag actual" aria-current="page" aria-label={`Página ${p}, actual`}>
                  {p}
                </span>
              ) : (
                <Link href={href(p)} className="lis-pag" aria-label={`Ir a la página ${p}`}>
                  {p}
                </Link>
              )}
            </li>
          ),
        )}
      </ol>
      {pagina < paginas ? (
        <Link href={href(pagina + 1)} rel="next" className="lis-pag lis-pag-flecha" aria-label="Página siguiente">
          <span>Siguiente</span> <Icono nombre="derecha" tam={18} />
        </Link>
      ) : (
        <span className="lis-pag lis-pag-flecha inactiva" aria-hidden="true">
          <span>Siguiente</span> <Icono nombre="derecha" tam={18} />
        </span>
      )}
    </nav>
  )
}
