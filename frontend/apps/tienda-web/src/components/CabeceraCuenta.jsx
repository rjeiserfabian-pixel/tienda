'use client'

import Link from 'next/link'
import Icono from './Icono'
import { useCarrito, useCuenta } from './Proveedores'

/** Botones de la cabecera: la cuenta del cliente y el carrito con su contador. */
export default function CabeceraCuenta() {
  const cuenta = useCuenta()
  const carrito = useCarrito()
  const nombre = cuenta?.perfil?.nombres?.split(' ')[0]
  const n = carrito?.cantidadTotal ?? 0
  return (
    <>
      <Link
        href={cuenta?.autenticado ? '/cuenta' : '/cuenta/ingresar'}
        className="cab-cuenta"
        aria-label={cuenta?.autenticado ? `Mi cuenta, ${nombre ?? ''}` : 'Ingresar a mi cuenta'}
      >
        <Icono nombre="usuario" tam={22} />
        <span className="cab-cuenta-texto">{cuenta?.autenticado ? (nombre ?? 'Mi cuenta') : 'Ingresar'}</span>
      </Link>
      <Link href="/carrito" className="cab-carrito" aria-label={n > 0 ? `Carrito, ${n} producto${n === 1 ? '' : 's'}` : 'Carrito vacío'}>
        <Icono nombre="carrito" tam={22} />
        {n > 0 && (
          <span className="cab-carrito-n" aria-hidden="true">
            {n > 99 ? '99+' : n}
          </span>
        )}
      </Link>
    </>
  )
}
