'use client'

import Icono from './Icono'
import { useFavoritos } from './ProveedorFavoritos'

/** El corazón: guarda o quita un producto de «Mis favoritos». Va fuera de los enlaces. */
export default function BotonFavorito({ producto, variante = 'tarjeta' }) {
  const favoritos = useFavoritos()
  if (!favoritos) return null
  const activo = favoritos.esFavorito(producto.id)
  return (
    <button
      type="button"
      className={`btn-favorito ${variante}${activo ? ' activo' : ''}`}
      aria-pressed={activo}
      aria-label={`${activo ? 'Quitar de mis favoritos' : 'Guardar en mis favoritos'}: ${producto.nombre}`}
      onClick={() => favoritos.alternar(producto.id)}
    >
      <Icono nombre="corazon" tam={variante === 'ficha' ? 20 : 18} fill={activo ? 'currentColor' : 'none'} />
      {variante === 'ficha' && <span>{activo ? 'En mis favoritos' : 'Guardar en favoritos'}</span>}
    </button>
  )
}
