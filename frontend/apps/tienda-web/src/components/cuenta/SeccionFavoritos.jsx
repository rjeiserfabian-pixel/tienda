'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import '@/app/listado.css'
import { ErrorTienda, llamar } from '@/lib/cliente'
import ProductoTarjeta from '../ProductoTarjeta'
import { useFavoritos } from '../ProveedorFavoritos'

/** «Mis favoritos»: los productos que el cliente guardó con el corazón. */
export default function SeccionFavoritos() {
  const favoritos = useFavoritos()
  const [productos, setProductos] = useState(null)
  const [fallo, setFallo] = useState(null)

  useEffect(() => {
    llamar('cuenta/favoritos?productos=1')
      .then((d) => setProductos(d.productos ?? []))
      .catch((e) => setFallo(e instanceof ErrorTienda ? e.message : 'No pudimos cargar tus favoritos.'))
  }, [])

  // Si se quita un corazón aquí, la tarjeta desaparece de la lista.
  const visibles = productos && favoritos ? productos.filter((p) => favoritos.esFavorito(p.id)) : productos

  return (
    <div className="cta-seccion">
      <h1>Mis favoritos</h1>
      {fallo && (
        <p className="alerta error" role="alert">
          {fallo}
        </p>
      )}
      {!fallo && visibles === null && <span className="esqueleto" style={{ height: 260, borderRadius: 14 }} aria-busy="true" />}
      {visibles && visibles.length === 0 && (
        <p className="cta-vacio">
          Aún no guardaste productos. Toca el corazón de un producto para tenerlo aquí.{' '}
          <Link href="/" className="enlace">
            Ver productos
          </Link>
        </p>
      )}
      {visibles && visibles.length > 0 && (
        <ul className="lis-rejilla">
          {visibles.map((p) => (
            <li key={p.id}>
              <ProductoTarjeta producto={p} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
