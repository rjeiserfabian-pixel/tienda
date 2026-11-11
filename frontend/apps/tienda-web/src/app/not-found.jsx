import Link from 'next/link'

export const metadata = { title: 'Página no encontrada', robots: { index: false } }

export default function NoEncontrada() {
  return (
    <main id="contenido" className="contenedor pagina">
      <div className="estado-vacio">
        <p className="insignia">Error 404</p>
        <h1 className="titulo-pagina">No encontramos esa página</h1>
        <p>Puede que el producto ya no esté disponible o que el enlace tenga un error.</p>
        <Link href="/" className="boton">
          Volver al inicio
        </Link>
      </div>
    </main>
  )
}
