'use client'

import Link from 'next/link'
import { useRef } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import Icono from '../Icono'
import { useCuenta } from '../Proveedores'
import useSesionRequerida from './useSesionRequerida'

const SECCIONES = [
  { href: '/cuenta', texto: 'Resumen' },
  { href: '/cuenta/datos', texto: 'Mis datos' },
  { href: '/cuenta/direcciones', texto: 'Mis direcciones' },
  { href: '/cuenta/pedidos', texto: 'Mis pedidos' },
  { href: '/cuenta/seguridad', texto: 'Seguridad' },
]

/** Marco de «Mi cuenta»: navegación (pestañas en celular, columna en pantallas grandes) y protección de sesión. */
export default function PanelCuenta({ children }) {
  const saliendo = useRef(false)
  const estado = useSesionRequerida(saliendo)
  const cuenta = useCuenta()
  const ruta = usePathname()
  const router = useRouter()

  if (estado !== 'autenticado') {
    return (
      <div className="contenedor cta-marco" aria-busy="true">
        <div className="cta-esqueleto" />
        <div className="cta-esqueleto grande" />
      </div>
    )
  }

  async function salir() {
    saliendo.current = true // salir a propósito no debe mandar a «ingresar»
    router.replace('/')
    await cuenta.salir()
  }

  return (
    <div className="contenedor cta-marco">
      <nav className="cta-nav" aria-label="Mi cuenta">
        <ul>
          {SECCIONES.map((s) => (
            <li key={s.href}>
              <Link href={s.href} aria-current={ruta === s.href ? 'page' : undefined}>
                {s.texto}
              </Link>
            </li>
          ))}
          <li>
            <button type="button" onClick={salir} className="cta-salir">
              <Icono nombre="cerrar" tam={16} /> Salir
            </button>
          </li>
        </ul>
      </nav>
      <section className="cta-contenido">{children}</section>
    </div>
  )
}
