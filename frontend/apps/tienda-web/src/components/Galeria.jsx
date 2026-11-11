'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Icono from './Icono'

/**
 * Galería de fotos del producto.
 * - Una sola pista horizontal con imán a cada foto: en celular se desliza con el dedo, en
 *   computadora se cambia con las miniaturas o las flechas.
 * - Un clic en la foto abre un visor grande (<dialog>) con flechas, teclado ← → y Escape.
 * - La primera foto lleva tamaño fijo y prioridad alta para que la página no «salte» al cargar.
 */
export default function Galeria({ fotos, nombre }) {
  const pista = useRef(null)
  const visor = useRef(null)
  const [actual, setActual] = useState(0)
  const [verGrande, setVerGrande] = useState(false)
  const total = fotos.length

  // Qué foto está a la vista, según el desplazamiento de la pista.
  const alDesplazar = useCallback(() => {
    const el = pista.current
    if (!el || !el.clientWidth) return
    setActual(Math.max(0, Math.min(total - 1, Math.round(el.scrollLeft / el.clientWidth))))
  }, [total])

  const irA = useCallback(
    (indice) => {
      const el = pista.current
      const i = (indice + total) % total
      if (el) el.scrollTo({ left: i * el.clientWidth, behavior: 'smooth' })
      setActual(i)
    },
    [total],
  )

  // El visor sigue a la foto elegida y cierra con Escape (lo hace <dialog>).
  useEffect(() => {
    const dialogo = visor.current
    if (!dialogo) return
    if (verGrande && !dialogo.open) dialogo.showModal()
    if (!verGrande && dialogo.open) dialogo.close()
  }, [verGrande])

  if (total === 0) {
    return (
      <div className="prod-galeria">
        <div className="prod-sin-foto" role="img" aria-label="Este producto aún no tiene fotos">
          Sin foto
        </div>
      </div>
    )
  }

  const alTeclear = (e) => {
    if (e.key === 'ArrowRight') {
      e.preventDefault()
      irA(actual + 1)
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault()
      irA(actual - 1)
    }
  }

  return (
    <div className="prod-galeria">
      <div className="prod-pista-caja">
        <ul
          className="prod-pista"
          ref={pista}
          onScroll={alDesplazar}
          aria-roledescription="carrusel"
          aria-label={`Fotos de ${nombre}`}
          tabIndex={0}
          onKeyDown={alTeclear}
        >
          {fotos.map((f, i) => (
            <li key={f.id} className="prod-diapositiva" aria-roledescription="foto" aria-label={`Foto ${i + 1} de ${total}`}>
              <button type="button" className="prod-ampliar" onClick={() => setVerGrande(true)} aria-label="Ver la foto en grande">
                <img
                  src={f.mini}
                  srcSet={`${f.mini} 400w, ${f.grande} 1600w`}
                  sizes="(min-width: 1100px) 560px, (min-width: 720px) 50vw, 100vw"
                  alt={i === 0 ? nombre : `${nombre}, foto ${i + 1}`}
                  width={800}
                  height={800}
                  loading={i === 0 ? 'eager' : 'lazy'}
                  fetchPriority={i === 0 ? 'high' : 'auto'}
                  decoding="async"
                />
              </button>
            </li>
          ))}
        </ul>
        {total > 1 && (
          <>
            <button type="button" className="prod-flecha izquierda" onClick={() => irA(actual - 1)} aria-label="Foto anterior">
              <Icono nombre="izquierda" tam={22} />
            </button>
            <button type="button" className="prod-flecha derecha" onClick={() => irA(actual + 1)} aria-label="Foto siguiente">
              <Icono nombre="derecha" tam={22} />
            </button>
          </>
        )}
        <span className="prod-zoom" aria-hidden="true">
          <Icono nombre="zoom" tam={18} />
        </span>
      </div>

      {total > 1 && (
        <>
          <ul className="prod-puntos" aria-hidden="true">
            {fotos.map((f, i) => (
              <li key={f.id} className={i === actual ? 'activo' : undefined} />
            ))}
          </ul>
          <ul className="prod-miniaturas" aria-label="Elegir foto">
            {fotos.map((f, i) => (
              <li key={f.id}>
                <button
                  type="button"
                  className={i === actual ? 'activa' : undefined}
                  onClick={() => irA(i)}
                  aria-label={`Ver la foto ${i + 1}`}
                  aria-current={i === actual ? 'true' : undefined}
                >
                  <img src={f.mini} alt="" width={96} height={96} loading="lazy" decoding="async" />
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      <dialog
        ref={visor}
        className="prod-visor"
        aria-label={`Fotos de ${nombre} en grande`}
        onClose={() => setVerGrande(false)}
        onKeyDown={alTeclear}
        onClick={(e) => e.target === visor.current && setVerGrande(false)}
      >
        <div className="prod-visor-caja">
          <button type="button" className="prod-visor-cerrar" onClick={() => setVerGrande(false)} aria-label="Cerrar">
            <Icono nombre="cerrar" tam={24} />
          </button>
          {verGrande && (
            <img
              src={fotos[actual].grande}
              alt={`${nombre}, foto ${actual + 1} de ${total}`}
              className="prod-visor-foto"
            />
          )}
          {total > 1 && (
            <>
              <button type="button" className="prod-flecha izquierda" onClick={() => irA(actual - 1)} aria-label="Foto anterior">
                <Icono nombre="izquierda" tam={24} />
              </button>
              <button type="button" className="prod-flecha derecha" onClick={() => irA(actual + 1)} aria-label="Foto siguiente">
                <Icono nombre="derecha" tam={24} />
              </button>
              <p className="prod-visor-cuenta" aria-live="polite">
                {actual + 1} / {total}
              </p>
            </>
          )}
        </div>
      </dialog>
    </div>
  )
}
