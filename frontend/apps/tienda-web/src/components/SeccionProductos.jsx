import Link from 'next/link'
import '@/app/inicio.css'
import ProductoTarjeta from './ProductoTarjeta'

/**
 * Una franja de productos con título y enlace «Ver todos».
 * `variante="carrusel"` desliza en horizontal (con imán a cada tarjeta); `"rejilla"` los reparte en filas.
 * Si no hay productos no dibuja nada (así nunca queda un hueco con solo el título).
 */
export default function SeccionProductos({ id, titulo, descripcion, productos, href, textoEnlace = 'Ver todos', variante = 'carrusel' }) {
  if (!productos?.length) return null
  const idTitulo = `${id}-titulo`
  return (
    <section className="ini-seccion" aria-labelledby={idTitulo}>
      <div className="contenedor">
        <div className="ini-seccion-cab">
          <div>
            <h2 id={idTitulo}>{titulo}</h2>
            {descripcion && <p className="subtitulo">{descripcion}</p>}
          </div>
          {href && (
            <Link href={href} className="ini-ver-todos">
              {textoEnlace} <span aria-hidden="true">→</span>
            </Link>
          )}
        </div>
        <ul className={variante === 'carrusel' ? 'ini-carrusel' : 'ini-rejilla'}>
          {productos.map((p, i) => (
            <li key={p.id}>
              <ProductoTarjeta producto={p} prioridad={i < 2 && variante === 'rejilla'} />
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
