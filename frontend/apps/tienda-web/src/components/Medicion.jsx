'use client'

import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'
import { guardarConsentimiento, leerConsentimiento, vaciarCola } from '@/lib/medicion'

const EVENTO_PREFERENCIAS = 'tienda:cookies'

/** Carga un script externo una sola vez. */
function cargarScript(src) {
  if (document.querySelector(`script[src="${src}"]`)) return
  const s = document.createElement('script')
  s.async = true
  s.src = src
  document.head.appendChild(s)
}

function iniciarGoogle(id) {
  if (typeof window.gtag === 'function') return
  window.dataLayer = window.dataLayer || []
  window.gtag = function gtag() {
    window.dataLayer.push(arguments) // eslint-disable-line prefer-rest-params
  }
  window.gtag('js', new Date())
  window.gtag('config', id, { send_page_view: false, anonymize_ip: true })
  cargarScript(`https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(id)}`)
}

function iniciarMeta(id) {
  if (typeof window.fbq === 'function') return
  const fbq = function fbq() {
    if (fbq.callMethod) fbq.callMethod.apply(fbq, arguments) // eslint-disable-line prefer-rest-params
    else fbq.queue.push(arguments) // eslint-disable-line prefer-rest-params
  }
  fbq.queue = []
  fbq.loaded = true
  fbq.version = '2.0'
  fbq.push = fbq
  window.fbq = fbq
  window._fbq = fbq
  cargarScript('https://connect.facebook.net/en_US/fbevents.js')
  window.fbq('init', id)
}

/**
 * Aviso de cookies y carga de la medición. Sin códigos configurados no hace nada (ni muestra el
 * aviso). Los scripts de Google y Meta SOLO se cargan si el visitante pulsa «Aceptar».
 */
export default function Medicion({ ga4, pixel }) {
  const ruta = usePathname()
  const hayMedicion = Boolean(ga4 || pixel)
  const [consentimiento, setConsentimiento] = useState(undefined) // undefined = aún no se lee
  const [abierto, setAbierto] = useState(false)

  useEffect(() => {
    if (!hayMedicion) return undefined
    const valor = leerConsentimiento()
    setConsentimiento(valor)
    setAbierto(valor === null)
    const reabrir = () => setAbierto(true)
    window.addEventListener(EVENTO_PREFERENCIAS, reabrir)
    return () => window.removeEventListener(EVENTO_PREFERENCIAS, reabrir)
  }, [hayMedicion])

  useEffect(() => {
    if (consentimiento !== 'si') return
    if (ga4) iniciarGoogle(ga4)
    if (pixel) iniciarMeta(pixel)
    vaciarCola()
  }, [consentimiento, ga4, pixel])

  // Una visita por página (también cuando se navega sin recargar).
  useEffect(() => {
    if (consentimiento !== 'si') return
    if (typeof window.gtag === 'function') window.gtag('event', 'page_view', { page_path: ruta })
    if (typeof window.fbq === 'function') window.fbq('track', 'PageView')
  }, [consentimiento, ruta])

  function decidir(valor) {
    guardarConsentimiento(valor)
    setConsentimiento(valor)
    setAbierto(false)
    if (valor === 'no') window.location.reload() // suelta lo que ya se hubiera cargado
  }

  if (!hayMedicion || !abierto) return null
  return (
    <section className="cookies" role="dialog" aria-modal="false" aria-labelledby="cookies-t">
      <div>
        <h2 id="cookies-t">Tu privacidad</h2>
        <p>
          Usamos cookies de medición para saber qué productos interesan y mejorar la tienda. Solo las activamos si las aceptas, y puedes cambiar de opinión cuando quieras desde «Preferencias de cookies», al pie de la página.
        </p>
      </div>
      <div className="cookies-acciones">
        <button type="button" className="boton secundario" onClick={() => decidir('no')}>
          Solo las necesarias
        </button>
        <button type="button" className="boton" onClick={() => decidir('si')}>
          Aceptar
        </button>
      </div>
    </section>
  )
}
