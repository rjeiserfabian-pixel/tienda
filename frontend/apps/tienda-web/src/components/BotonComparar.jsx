'use client'

import Icono from './Icono'
import { useComparar } from './ProveedorComparar'

/**
 * Botón «Comparar» (casilla): agrega o quita un producto de la comparación.
 * `producto` necesita: id, nombre, foto (miniatura) y categoria: { slug }.
 * Va fuera de los enlaces (un botón dentro de un enlace no es válido ni accesible).
 */
export default function BotonComparar({ producto, variante = 'tarjeta' }) {
  const comparar = useComparar()
  if (!comparar) return null
  const activo = comparar.tiene(producto.id)
  return (
    <button
      type="button"
      className={`btn-comparar ${variante}${activo ? ' activo' : ''}`}
      aria-pressed={activo}
      aria-label={`${activo ? 'Quitar de la comparación' : 'Comparar'}: ${producto.nombre}`}
      onClick={() => (activo ? comparar.quitar(producto.id) : comparar.agregar(producto))}
    >
      <Icono nombre={activo ? 'check' : 'comparar'} tam={16} />
      <span>{activo ? (variante === 'tarjeta' ? 'Elegido' : 'Comparando') : 'Comparar'}</span>
    </button>
  )
}
