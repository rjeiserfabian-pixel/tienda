import { useState } from 'react'
import { Icono } from '../../../shared/components/IconosPanel'
import ClienteVenta from './ClienteVenta'

/**
 * A quién va la mercadería: por defecto el cliente de la venta, pero se puede cambiar por otro cliente
 * registrado (por ejemplo, cuando se entrega a un tercero) y volver al de la venta.
 */
export default function DestinatarioGuia({ original, elegido, onElegir, disabled }) {
  const [cambiando, setCambiando] = useState(false)
  // El cliente de la venta llega como `documento`; un cliente elegido, como `numero_documento`.
  const quien = elegido ? { nombre: elegido.nombre, tipo_documento: elegido.tipo_documento, documento: elegido.numero_documento } : original

  if (cambiando) {
    return (
      <div className="pos-bloques">
        <ClienteVenta
          cliente={null}
          disabled={disabled}
          onElegir={(cliente) => {
            if (cliente) onElegir(cliente)
            setCambiando(false)
          }}
        />
        <button type="button" className="pos-enlace" onClick={() => setCambiando(false)}>
          Cancelar el cambio
        </button>
      </div>
    )
  }
  return (
    <div className="compra-proveedor-elegido">
      <span className="compra-proveedor-icono" aria-hidden="true">
        <Icono nombre="user" tam={22} />
      </span>
      <div className="compra-proveedor-datos">
        <strong>{quien.nombre || 'Clientes varios'}</strong>
        <span className="sub-texto">{quien.documento ? `${quien.tipo_documento} ${quien.documento}` : 'Sin documento'}</span>
      </div>
      {!disabled && (
        <>
          <button type="button" onClick={() => setCambiando(true)}>
            Cambiar destinatario
          </button>
          {elegido && (
            <button type="button" onClick={() => onElegir(null)}>
              Volver al cliente de la venta
            </button>
          )}
        </>
      )}
    </div>
  )
}
