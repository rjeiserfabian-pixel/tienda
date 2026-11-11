'use client'

import Link from 'next/link'
import { useEffect } from 'react'
import Icono from './Icono'
import { useCarrito } from './Proveedores'

const DURACION_MS = 6000

/** Aviso no invasivo al agregar un producto: foto, nombre y enlaces. Se cierra solo. */
export default function AvisoCarrito() {
  const carrito = useCarrito()
  const aviso = carrito?.aviso
  const cerrar = carrito?.cerrarAviso

  useEffect(() => {
    if (!aviso) return undefined
    const t = setTimeout(cerrar, DURACION_MS)
    return () => clearTimeout(t)
  }, [aviso, cerrar])

  return (
    <div className="aviso-carrito-zona" aria-live="polite" aria-atomic="true">
      {aviso && (
        <div className="aviso-carrito" role="status" key={aviso.momento}>
          {aviso.foto ? <img src={aviso.foto} alt="" width={56} height={56} /> : <span className="aviso-carrito-sin" aria-hidden="true" />}
          <div className="aviso-carrito-texto">
            <p>
              <Icono nombre="check" tam={16} /> Agregado al carrito
            </p>
            {aviso.nombre && <strong>{aviso.nombre}</strong>}
          </div>
          <div className="aviso-carrito-botones">
            <Link href="/carrito" className="boton chico" onClick={cerrar}>
              Ver carrito
            </Link>
            <button type="button" className="boton chico secundario" onClick={cerrar}>
              Seguir comprando
            </button>
          </div>
          <button type="button" className="aviso-carrito-x" onClick={cerrar} aria-label="Cerrar aviso">
            <Icono nombre="cerrar" tam={16} />
          </button>
        </div>
      )}
    </div>
  )
}
