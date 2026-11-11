'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { ErrorTienda, llamar } from '@/lib/cliente'
import { soles } from '@/lib/format'
import { claseEstado, fechaCorta, textoEstado } from '@/lib/pago'
import Icono from '../Icono'

/** «Mis pedidos»: los pedidos del cliente, del más nuevo al más antiguo. */
export default function ListaPedidos() {
  const [pagina, setPagina] = useState(1)
  const [datos, setDatos] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let vigente = true
    llamar(`pedidos?page=${pagina}`)
      .then((d) => {
        if (!vigente) return
        setDatos(d)
        setError(null)
      })
      .catch((e) => vigente && setError(e instanceof ErrorTienda ? e.message : 'No pudimos cargar tus pedidos.'))
    return () => {
      vigente = false
    }
  }, [pagina])

  if (error) {
    return (
      <p className="alerta error" role="alert">
        <Icono nombre="info" tam={18} /> <span>{error}</span>
      </p>
    )
  }
  if (!datos) return <span className="esqueleto" style={{ height: 240, borderRadius: 14 }} aria-busy="true" />
  if (datos.results.length === 0) {
    return (
      <div className="cta-proximamente">
        <Icono nombre="carrito" tam={32} />
        <h2>Aún no tienes pedidos</h2>
        <p>Cuando compres, aquí verás tus pedidos, sus comprobantes y su estado.</p>
        <Link href="/" className="boton">
          Empezar a comprar
        </Link>
      </div>
    )
  }
  return (
    <>
      <ul className="ped-lista">
        {datos.results.map((p) => (
          <li key={p.numero}>
            <Link href={`/cuenta/pedidos/${p.numero}`} className="ped-fila">
              <span>
                <strong>{p.numero}</strong>
                <small>{fechaCorta(p.creado_en)}</small>
              </span>
              <span className={`insignia ${claseEstado(p.estado)}`}>{textoEstado(p.estado)}</span>
              <strong className="ped-fila-total">{soles(p.total)}</strong>
              <Icono nombre="derecha" tam={18} />
            </Link>
          </li>
        ))}
      </ul>
      {datos.paginas > 1 && (
        <nav className="ped-paginas" aria-label="Páginas de pedidos">
          <button type="button" className="boton secundario chico" disabled={pagina <= 1} onClick={() => setPagina((n) => n - 1)}>
            Anteriores
          </button>
          <span>
            Página {datos.page} de {datos.paginas}
          </span>
          <button type="button" className="boton secundario chico" disabled={pagina >= datos.paginas} onClick={() => setPagina((n) => n + 1)}>
            Siguientes
          </button>
        </nav>
      )}
    </>
  )
}
