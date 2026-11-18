'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { useState } from 'react'
import { ErrorTienda, llamar } from '@/lib/cliente'

/**
 * «Darme de baja» de los avisos de garantía por vencer. Pide un clic de confirmación (no se da de baja
 * solo al abrir el enlace: algunos programas de correo abren los enlaces por su cuenta).
 */
export default function BajaAvisosGarantia() {
  const token = useSearchParams().get('t') ?? ''
  const [estado, setEstado] = useState(token ? 'pregunta' : 'sin_enlace') // pregunta | enviando | ok | invalido | error

  async function confirmar() {
    setEstado('enviando')
    try {
      await llamar('garantia/baja', { metodo: 'POST', cuerpo: { token } })
      setEstado('ok')
    } catch (error) {
      setEstado(error instanceof ErrorTienda && error.estado === 400 ? 'invalido' : 'error')
    }
  }

  if (estado === 'ok') {
    return (
      <div className="tarjeta-centrada">
        <h1>Listo, ya no recibirás estos avisos</h1>
        <p className="sub">Dejamos de enviarte avisos de garantías por vencer. Tu garantía sigue vigente y puedes consultarla cuando quieras.</p>
        <div className="form-acciones" style={{ marginTop: 18 }}>
          <Link href="/garantia" className="boton">
            Consultar mi garantía
          </Link>
        </div>
      </div>
    )
  }
  if (estado === 'sin_enlace' || estado === 'invalido') {
    return (
      <div className="tarjeta-centrada">
        <h1>Este enlace no es válido</h1>
        <p className="sub">Abre el enlace de «darte de baja» desde el correo que recibiste. Si ya no te sirve, escríbenos y lo resolvemos.</p>
        <div className="form-acciones" style={{ marginTop: 18 }}>
          <Link href="/" className="boton">
            Ir a la tienda
          </Link>
        </div>
      </div>
    )
  }
  return (
    <div className="tarjeta-centrada">
      <h1>¿Dejar de recibir avisos de garantía?</h1>
      <p className="sub">Ya no te escribiremos cuando una de tus garantías esté por vencer. Tus garantías no cambian.</p>
      {estado === 'error' && (
        <p className="alerta error" role="alert">
          No pudimos darte de baja ahora. Inténtalo de nuevo en un momento.
        </p>
      )}
      <div className="form-acciones" style={{ marginTop: 18 }}>
        <button type="button" className="boton" onClick={confirmar} disabled={estado === 'enviando'}>
          {estado === 'enviando' ? 'Un momento…' : 'Sí, darme de baja'}
        </button>
        <Link href="/" className="boton secundario">
          No, seguir recibiéndolos
        </Link>
      </div>
    </div>
  )
}
