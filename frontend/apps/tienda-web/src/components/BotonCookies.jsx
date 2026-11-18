'use client'

/** Vuelve a abrir el aviso de cookies (solo se ofrece si el negocio configuró la medición). */
export default function BotonCookies() {
  return (
    <button type="button" className="enlace-pie" onClick={() => window.dispatchEvent(new Event('tienda:cookies'))}>
      Preferencias de cookies
    </button>
  )
}
