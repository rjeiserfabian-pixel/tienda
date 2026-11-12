'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import Icono from './Icono'
import { useCarrito, useCuenta } from './Proveedores'

// Pantallas que ya tienen su propia barra fija abajo (compra, ficha, armador, comparador): ahí no se muestra.
const SIN_BARRA = ['/producto', '/compra', '/carrito', '/arma-tu-pc', '/comparar']

/** Barra de navegación inferior del celular: Inicio, Categorías, Carrito y Cuenta. Solo navega; no guarda nada. */
export default function BarraInferior() {
  const ruta = usePathname() ?? '/'
  const carrito = useCarrito()
  const cuenta = useCuenta()
  if (SIN_BARRA.some((r) => ruta === r || ruta.startsWith(`${r}/`))) return null
  const n = carrito?.cantidadTotal ?? 0
  const enCuenta = ruta.startsWith('/cuenta')
  return (
    <nav className="barra-inf" aria-label="Navegación rápida">
      <ul>
        <li>
          <Link href="/" aria-current={ruta === '/' ? 'page' : undefined}>
            <Icono nombre="casa" tam={22} />
            <span>Inicio</span>
          </Link>
        </li>
        <li>
          <Link href="/#categorias">
            <Icono nombre="cuadricula" tam={22} />
            <span>Categorías</span>
          </Link>
        </li>
        <li>
          <Link href="/carrito" aria-label={n > 0 ? `Carrito, ${n} producto${n === 1 ? '' : 's'}` : 'Carrito'}>
            <span className="barra-inf-icono">
              <Icono nombre="carrito" tam={22} />
              {n > 0 && <b aria-hidden="true">{n > 99 ? '99+' : n}</b>}
            </span>
            <span>Carrito</span>
          </Link>
        </li>
        <li>
          <Link href={cuenta?.autenticado ? '/cuenta' : '/cuenta/ingresar'} aria-current={enCuenta ? 'page' : undefined}>
            <Icono nombre="usuario" tam={22} />
            <span>Cuenta</span>
          </Link>
        </li>
      </ul>
    </nav>
  )
}
