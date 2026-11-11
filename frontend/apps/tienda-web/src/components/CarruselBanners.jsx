'use client'

import Link from 'next/link'
import { useCallback, useEffect, useRef, useState } from 'react'
import '@/app/banners.css'
import Icono from './Icono'

const CADA_MS = 6500
// Mismas reglas que el servidor: una página de la tienda («/ofertas») o una URL https. Nada más.
const INTERNO = /^\/(?!\/)[A-Za-z0-9\-._~/%?=&#]*$/
const HTTPS = /^https:\/\/\S+$/

/** Contenido de un banner: la imagen (escritorio o celular) y, encima, su texto. */
function Diapositiva({ banner: b, indice, usarMovil, total }) {
  const interno = b.enlace && INTERNO.test(b.enlace)
  const externo = b.enlace && !interno && HTTPS.test(b.enlace)
  const contenido = (
    <>
      <picture>
        {usarMovil && b.imagen_movil && <source media="(max-width: 767px)" srcSet={b.imagen_movil} />}
        <img
          src={b.imagen_escritorio}
          alt={b.alt}
          width={1600}
          height={600}
          loading={indice === 0 ? 'eager' : 'lazy'}
          fetchPriority={indice === 0 ? 'high' : 'auto'}
          decoding="async"
          draggable="false"
        />
      </picture>
      <div className="banner-texto">
        <h2>{b.titulo}</h2>
        {b.subtitulo && <p>{b.subtitulo}</p>}
        {b.boton_texto && (interno || externo) && <span className="boton">{b.boton_texto}</span>}
      </div>
    </>
  )
  const propiedades = {
    className: 'banner-diapositiva',
    role: 'group',
    'aria-roledescription': 'diapositiva',
    'aria-label': `${indice + 1} de ${total}`,
  }
  if (interno) {
    return (
      <Link href={b.enlace} {...propiedades}>
        {contenido}
      </Link>
    )
  }
  if (externo) {
    return (
      <a href={b.enlace} target="_blank" rel="noopener noreferrer" {...propiedades}>
        {contenido}
      </a>
    )
  }
  return <div {...propiedades}>{contenido}</div>
}

/**
 * Carrusel de banners del inicio.
 *
 * Funciona SIN JavaScript (es una tira con «imán» que se desliza con el dedo o la rueda). Con JavaScript
 * agrega flechas, puntos y avance automático que se detiene al pasar el mouse, al enfocar, al tocar,
 * con «reducir movimiento» del sistema, con la pestaña oculta o si la persona lo pausa.
 * El alto está fijo por CSS (aspect-ratio): no mueve la página al cargar.
 */
export default function CarruselBanners({ banners }) {
  const pista = useRef(null)
  const [activo, setActivo] = useState(0)
  const [pausaManual, setPausaManual] = useState(false)
  const [pausaTemporal, setPausaTemporal] = useState(false)
  const [reducido, setReducido] = useState(false)
  const [oculta, setOculta] = useState(false)
  const total = banners.length
  // En celular se usa la imagen cuadrada solo si TODOS los banners la tienen (así el alto no salta).
  const usarMovil = banners.every((b) => b.imagen_movil)

  useEffect(() => {
    const consulta = window.matchMedia('(prefers-reduced-motion: reduce)')
    setReducido(consulta.matches)
    const alCambiar = (e) => setReducido(e.matches)
    consulta.addEventListener('change', alCambiar)
    const visibilidad = () => setOculta(document.hidden)
    document.addEventListener('visibilitychange', visibilidad)
    return () => {
      consulta.removeEventListener('change', alCambiar)
      document.removeEventListener('visibilitychange', visibilidad)
    }
  }, [])

  const ir = useCallback(
    (indice) => {
      const el = pista.current
      if (!el) return
      const destino = (indice + total) % total
      el.scrollTo({ left: destino * el.clientWidth, behavior: reducido ? 'auto' : 'smooth' })
    },
    [total, reducido],
  )

  // El punto activo sigue a la tira cuando se desliza (con el dedo, con flechas o solo).
  const alDeslizar = useCallback(() => {
    const el = pista.current
    if (!el || !el.clientWidth) return
    setActivo(Math.round(el.scrollLeft / el.clientWidth))
  }, [])

  const automatico = total > 1 && !pausaManual && !pausaTemporal && !reducido && !oculta
  useEffect(() => {
    if (!automatico) return undefined
    const t = setInterval(() => ir(activo + 1), CADA_MS)
    return () => clearInterval(t)
  }, [automatico, activo, ir])

  return (
    <section className="contenedor banner-carrusel-caja" aria-roledescription="carrusel" aria-label="Promociones">
      <div
        className="banner-carrusel"
        data-movil={usarMovil ? 'cuadrada' : 'ancha'}
        onMouseEnter={() => setPausaTemporal(true)}
        onMouseLeave={() => setPausaTemporal(false)}
        onFocus={() => setPausaTemporal(true)}
        onBlur={() => setPausaTemporal(false)}
        onTouchStart={() => {
          // Al tocar se detiene un rato y luego vuelve a avanzar solo.
          setPausaTemporal(true)
          window.setTimeout(() => setPausaTemporal(false), 9000)
        }}
      >
        <div className="banner-pista" ref={pista} onScroll={alDeslizar} tabIndex={0} aria-live={automatico ? 'off' : 'polite'}>
          {banners.map((b, i) => (
            <Diapositiva key={b.id} banner={b} indice={i} total={total} usarMovil={usarMovil} />
          ))}
        </div>

        {total > 1 && (
          <>
            <button type="button" className="banner-flecha anterior" aria-label="Banner anterior" onClick={() => ir(activo - 1)}>
              <Icono nombre="izquierda" tam={22} />
            </button>
            <button type="button" className="banner-flecha siguiente" aria-label="Banner siguiente" onClick={() => ir(activo + 1)}>
              <Icono nombre="derecha" tam={22} />
            </button>
            <div className="banner-controles">
              <ul className="banner-puntos">
                {banners.map((b, i) => (
                  <li key={b.id}>
                    <button type="button" aria-label={`Ir al banner ${i + 1}: ${b.titulo}`} aria-current={i === activo ? 'true' : undefined} onClick={() => ir(i)} />
                  </li>
                ))}
              </ul>
              {!reducido && (
                <button
                  type="button"
                  className="banner-pausa"
                  aria-pressed={pausaManual}
                  aria-label={pausaManual ? 'Reanudar el avance automático' : 'Pausar el avance automático'}
                  onClick={() => setPausaManual((v) => !v)}
                >
                  {pausaManual ? '▶' : '❚❚'}
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </section>
  )
}
