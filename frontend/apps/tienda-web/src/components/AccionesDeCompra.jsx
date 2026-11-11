'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { enlaceWhatsapp, urlAbsoluta } from '@/lib/format'
import Icono from './Icono'
import { useCarrito } from './Proveedores'

const MAX = 99

/**
 * Las acciones para comprar un producto: agregar al carrito, comprar ahora y consultar por WhatsApp.
 *
 * `compacto` es la versión de la barra fija del celular (un solo botón). El número de WhatsApp
 * lo administra el negocio en el panel y llega por `whatsapp`.
 */
export default function AccionesDeCompra({ producto, compacto = false, whatsapp }) {
  const router = useRouter()
  const carrito = useCarrito()
  const [cantidad, setCantidad] = useState(1)
  const agotado = producto.disponibilidad === 'agotado'
  const sinPrecio = producto.consultar_precio
  const tope = producto.disponibilidad === 'pocas' && producto.unidades ? Math.min(producto.unidades, MAX) : MAX
  const enCarrito = carrito?.items.find((l) => l.producto === producto.id)?.cantidad ?? 0

  const mensaje = [
    `Hola, me interesa este producto: ${producto.nombre}`,
    `Código: ${producto.codigo}`,
    urlAbsoluta(`/producto/${producto.slug}`),
  ].join('\n')
  const enlace = enlaceWhatsapp(mensaje, whatsapp)
  const textoConsulta = agotado ? 'Consultar disponibilidad' : sinPrecio ? 'Consultar precio' : 'Consultar por WhatsApp'
  const puedeComprar = !agotado && !sinPrecio

  const datos = { nombre: producto.nombre, foto: producto.fotos?.[0]?.mini ?? null }
  const agregar = () => carrito.agregar(producto.id, cantidad, datos)
  const comprarAhora = () => {
    // Si ya está en el carrito no se suma de nuevo: se va directo a pagar.
    if (enCarrito === 0) carrito.agregar(producto.id, cantidad, datos)
    router.push('/carrito')
  }

  const botonWhatsapp = enlace && (
    <a
      className={`boton whatsapp ${compacto ? '' : 'grande'} prod-boton-comprar`}
      href={enlace}
      target="_blank"
      rel="noopener noreferrer"
    >
      <Icono nombre="chat" tam={20} /> {textoConsulta}
    </a>
  )

  if (!puedeComprar) {
    if (botonWhatsapp) return botonWhatsapp
    return compacto ? null : (
      <p className="prod-aviso" role="note">
        <Icono nombre="info" tam={18} /> {agotado ? 'Este producto está agotado por ahora.' : 'Escríbenos para cotizar este producto.'}
      </p>
    )
  }

  if (compacto) {
    return (
      <button type="button" className="boton prod-boton-comprar" onClick={agregar} disabled={!carrito}>
        <Icono nombre="carrito" tam={20} /> Agregar al carrito
      </button>
    )
  }

  return (
    <div className="acc-compra">
      <div className="acc-fila">
        <div className="acc-cantidad" role="group" aria-label="Cantidad">
          <button type="button" onClick={() => setCantidad((c) => Math.max(1, c - 1))} disabled={cantidad <= 1} aria-label="Una unidad menos">
            <Icono nombre="menos" tam={18} />
          </button>
          <output aria-live="polite" aria-label={`${cantidad} unidades`}>
            {cantidad}
          </output>
          <button type="button" onClick={() => setCantidad((c) => Math.min(tope, c + 1))} disabled={cantidad >= tope} aria-label="Una unidad más">
            <Icono nombre="mas" tam={18} />
          </button>
        </div>
        <button type="button" className="boton grande acc-agregar" onClick={agregar} disabled={!carrito}>
          <Icono nombre="carrito" tam={20} /> Agregar al carrito
        </button>
      </div>
      <button type="button" className="boton secundario grande" onClick={comprarAhora} disabled={!carrito}>
        Comprar ahora
      </button>
      {enCarrito > 0 && (
        <p className="acc-en-carrito" role="status">
          <Icono nombre="check" tam={16} /> Ya tienes {enCarrito} en tu carrito
        </p>
      )}
      {botonWhatsapp && <div className="acc-whatsapp">{botonWhatsapp}</div>}
    </div>
  )
}
