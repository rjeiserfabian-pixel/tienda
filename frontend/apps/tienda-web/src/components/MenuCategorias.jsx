'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useId, useRef, useState } from 'react'
import Icono from './Icono'

/**
 * «Todas las categorías»: un panel con las familias y sus categorías (para computadora).
 * Se abre con clic o con el teclado, y se cierra al elegir algo, al tocar fuera o con Escape.
 */
export default function MenuCategorias({ familias }) {
  const id = useId()
  const pathname = usePathname()
  const raiz = useRef(null)
  const [abierto, setAbierto] = useState(false)

  useEffect(() => setAbierto(false), [pathname])

  useEffect(() => {
    if (!abierto) return undefined
    const fuera = (e) => {
      if (raiz.current && !raiz.current.contains(e.target)) setAbierto(false)
    }
    const tecla = (e) => e.key === 'Escape' && setAbierto(false)
    document.addEventListener('pointerdown', fuera)
    document.addEventListener('keydown', tecla)
    return () => {
      document.removeEventListener('pointerdown', fuera)
      document.removeEventListener('keydown', tecla)
    }
  }, [abierto])

  if (!familias?.length) return null
  return (
    <div className="mega" ref={raiz}>
      <button
        type="button"
        className="mega-boton"
        aria-expanded={abierto}
        aria-controls={id}
        onClick={() => setAbierto((a) => !a)}
      >
        <Icono nombre="menu" tam={18} /> Todas las categorías{' '}
        <Icono nombre="chevron" tam={16} className={abierto ? 'girado' : undefined} />
      </button>
      {abierto && (
        <div className="mega-panel" id={id}>
          <div className="mega-rejilla">
            {familias.map((f) => (
              <section key={f.slug} className="mega-familia" aria-label={f.nombre}>
                <h3>
                  <Link href={`/familia/${f.slug}`}>{f.nombre}</Link>
                </h3>
                <ul>
                  {f.categorias.map((c) => (
                    <li key={c.slug}>
                      <Link href={`/categoria/${c.slug}`}>
                        {c.nombre} <small>{c.cantidad}</small>
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
