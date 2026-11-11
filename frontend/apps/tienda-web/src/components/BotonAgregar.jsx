'use client'

import Icono from './Icono'
import { useCarrito } from './Proveedores'

/** Botón «Agregar» de la tarjeta de un producto (va fuera del enlace de la tarjeta). */
export default function BotonAgregar({ producto }) {
  const carrito = useCarrito()
  return (
    <button
      type="button"
      className="tar-agregar"
      disabled={!carrito}
      onClick={() => carrito.agregar(producto.id, 1, { nombre: producto.nombre, foto: producto.foto })}
      aria-label={`Agregar al carrito: ${producto.nombre}`}
    >
      <Icono nombre="carrito" tam={18} /> <span>Agregar</span>
    </button>
  )
}
