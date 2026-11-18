'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { ErrorTienda, llamar } from '@/lib/cliente'
import ListaGarantias from '../garantia/ListaGarantias'

/** «Mis garantías»: la garantía de los productos que el cliente ya recibió o está por recibir. */
export default function SeccionGarantias() {
  const [garantias, setGarantias] = useState(null)
  const [fallo, setFallo] = useState(null)

  useEffect(() => {
    llamar('cuenta/garantias')
      .then((d) => setGarantias(d.results ?? []))
      .catch((e) => setFallo(e instanceof ErrorTienda ? e.message : 'No pudimos cargar tus garantías.'))
  }, [])

  return (
    <div className="cta-seccion">
      <h1>Mis garantías</h1>
      <p className="sub">Aquí ves hasta cuándo vale la garantía de lo que compraste. También puedes consultarla con la serie de tu producto en «Consulta tu garantía».</p>
      {fallo && (
        <p className="alerta error" role="alert">
          {fallo}
        </p>
      )}
      {!fallo && garantias === null && <span className="esqueleto" style={{ height: 120, borderRadius: 14 }} aria-busy="true" />}
      {garantias && garantias.length === 0 && (
        <p className="cta-vacio">
          Cuando recibas productos con garantía, aparecerán aquí.{' '}
          <Link href="/garantia" className="enlace">
            Consultar con la serie
          </Link>
        </p>
      )}
      {garantias && garantias.length > 0 && <ListaGarantias garantias={garantias} conPedido />}
    </div>
  )
}
