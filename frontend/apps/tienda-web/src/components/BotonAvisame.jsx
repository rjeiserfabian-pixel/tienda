'use client'

import { useState } from 'react'
import Icono from './Icono'
import { useFavoritos } from './ProveedorFavoritos'

/** «Avísame cuando llegue»: para un producto agotado, se le escribe al cliente cuando vuelva el stock. */
export default function BotonAvisame({ producto }) {
  const favoritos = useFavoritos()
  const [error, setError] = useState(null)
  if (!favoritos) return null
  const pedido = favoritos.tieneAviso(producto.id)

  async function alternar() {
    setError(null)
    const problema = await favoritos.alternarAviso(producto.id)
    if (problema) setError(problema)
  }

  return (
    <div className="avisame">
      <button type="button" className={`boton ${pedido ? 'secundario' : ''} grande prod-boton-comprar`} onClick={alternar} disabled={favoritos.ocupado} aria-pressed={pedido}>
        <Icono nombre="campana" tam={20} /> {pedido ? 'Te avisaremos: cancelar aviso' : 'Avísame cuando llegue'}
      </button>
      {pedido && (
        <p className="com-chico" role="status">
          Te escribiremos por correo una sola vez, apenas vuelva a haber stock.
        </p>
      )}
      {error && (
        <p className="campo-error" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
