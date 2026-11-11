'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useRef } from 'react'
import Buscador from './Buscador'
import Icono from './Icono'

/**
 * Menú para celular y tablet: un panel que se desliza desde la izquierda. Usa <dialog> para que el
 * foco quede dentro y Escape lo cierre sin código extra.
 */
export default function MenuMovil({ familias, marcas, nombre }) {
  const dialogo = useRef(null)
  const pathname = usePathname()

  useEffect(() => {
    dialogo.current?.close()
  }, [pathname])

  const abrir = () => dialogo.current?.showModal()
  const cerrar = () => dialogo.current?.close()

  return (
    <>
      <button type="button" className="cab-icono solo-movil" aria-label="Abrir el menú" onClick={abrir}>
        <Icono nombre="menu" tam={24} />
      </button>
      <dialog
        ref={dialogo}
        className="menu-movil"
        aria-label={`Menú de ${nombre}`}
        onClick={(e) => {
          // Un toque en el fondo oscuro (el propio <dialog>) lo cierra; en un enlace, también.
          if (e.target === dialogo.current || e.target.closest('a')) cerrar()
        }}
      >
        <div className="menu-movil-panel">
          <div className="menu-movil-cabecera">
            <strong>{nombre}</strong>
            <button type="button" className="cab-icono" aria-label="Cerrar el menú" onClick={cerrar}>
              <Icono nombre="cerrar" tam={22} />
            </button>
          </div>
          <div className="menu-movil-buscar">
            <Buscador etiqueta="Buscar productos" alNavegar={cerrar} />
          </div>
          <nav aria-label="Categorías">
            <ul className="menu-movil-lista">
              <li>
                <Link href="/buscar?nuevo=1">Novedades</Link>
              </li>
              <li>
                <Link href="/buscar?destacado=1">Destacados</Link>
              </li>
              {familias.map((f) => (
                <li key={f.slug}>
                  <details>
                    <summary>
                      {f.nombre} <Icono nombre="chevron" tam={18} />
                    </summary>
                    <ul>
                      <li>
                        <Link href={`/familia/${f.slug}`}>Ver todo en {f.nombre}</Link>
                      </li>
                      {f.categorias.map((c) => (
                        <li key={c.slug}>
                          <Link href={`/categoria/${c.slug}`}>
                            {c.nombre} <small>{c.cantidad}</small>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </details>
                </li>
              ))}
              {marcas.length > 0 && (
                <li>
                  <details>
                    <summary>
                      Marcas <Icono nombre="chevron" tam={18} />
                    </summary>
                    <ul>
                      {marcas.map((m) => (
                        <li key={m.slug}>
                          <Link href={`/marca/${m.slug}`}>
                            {m.nombre} <small>{m.cantidad}</small>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </details>
                </li>
              )}
            </ul>
          </nav>
        </div>
      </dialog>
    </>
  )
}
