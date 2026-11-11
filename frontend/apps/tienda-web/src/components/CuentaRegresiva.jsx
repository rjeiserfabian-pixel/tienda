'use client'

import { useRouter } from 'next/navigation'
import { useEffect, useRef } from 'react'
import { desglosar, useAhora } from '@/lib/reloj'

const dos = (n) => String(n).padStart(2, '0')

/** Texto completo para lectores de pantalla (se actualiza por minuto, no por segundo). */
function textoAccesible({ dias, horas, minutos }) {
  const partes = []
  if (dias) partes.push(`${dias} ${dias === 1 ? 'día' : 'días'}`)
  if (horas) partes.push(`${horas} ${horas === 1 ? 'hora' : 'horas'}`)
  partes.push(`${minutos} ${minutos === 1 ? 'minuto' : 'minutos'}`)
  return `La oferta termina en ${partes.join(', ')}`
}

/**
 * Cuenta regresiva de una oferta.
 *
 * - Usa la hora del SERVIDOR (corrige el reloj del equipo) y un solo temporizador para toda la página.
 * - No mueve el diseño: antes de estar lista ocupa el mismo espacio (`min-height` en el CSS).
 * - Al llegar a cero muestra «La oferta terminó» y pide a la página actualizar su precio.
 * - `compacta` (tarjetas): una línea corta «Termina en 2 d 04 h»; completa (ficha): cajitas con segundos.
 */
export default function CuentaRegresiva({ terminaEn, compacta = false }) {
  const router = useRouter()
  const ahora = useAhora()
  const fin = Date.parse(terminaEn)
  const avisada = useRef(false)
  const faltan = ahora === null || !Number.isFinite(fin) ? null : fin - ahora
  const terminada = faltan !== null && faltan <= 0

  // Cuando termina, la página vuelve a pedir su información (con el precio normal). Se reintenta una
  // vez más por si lo guardado en la tienda tardó un momento en renovarse.
  useEffect(() => {
    if (!terminada || avisada.current) return undefined
    avisada.current = true
    const a = setTimeout(() => router.refresh(), 1500)
    const b = setTimeout(() => router.refresh(), 65_000)
    return () => {
      clearTimeout(a)
      clearTimeout(b)
    }
  }, [terminada, router])

  if (!Number.isFinite(fin)) return null
  const t = faltan === null ? null : desglosar(faltan)

  if (compacta) {
    return (
      <p className="cuenta-compacta" role="timer" aria-label={t && !terminada ? textoAccesible(t) : undefined}>
        {terminada ? (
          'La oferta terminó'
        ) : t ? (
          <>
            <span aria-hidden="true">Termina en </span>
            <b aria-hidden="true">{t.dias > 0 ? `${t.dias} d ${dos(t.horas)} h` : `${dos(t.horas)}:${dos(t.minutos)}:${dos(t.segundos)}`}</b>
          </>
        ) : (
          <span aria-hidden="true">&nbsp;</span>
        )}
      </p>
    )
  }

  return (
    <div className="cuenta" role="timer" aria-label={t && !terminada ? textoAccesible(t) : undefined}>
      <p className="cuenta-titulo">{terminada ? 'La oferta terminó' : 'La oferta termina en'}</p>
      {!terminada && (
        <ol className="cuenta-cajas" aria-hidden="true">
          {[
            ['días', t?.dias],
            ['horas', t?.horas],
            ['min', t?.minutos],
            ['seg', t?.segundos],
          ].map(([nombre, valor]) => (
            <li key={nombre}>
              <b>{valor === undefined || valor === null ? '--' : dos(valor)}</b>
              <small>{nombre}</small>
            </li>
          ))}
        </ol>
      )}
      {terminada && <p className="cuenta-nota">Estamos actualizando el precio…</p>}
    </div>
  )
}
