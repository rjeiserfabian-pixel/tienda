'use client'

import Link from 'next/link'
import { soles, urlFoto } from '@/lib/format'
import Icono from './Icono'
import { useCarrito } from './Proveedores'

const MAX = 99

function Esqueleto({ n }) {
  return (
    <ul className="car-lineas" aria-busy="true" aria-label="Cargando tu carrito">
      {Array.from({ length: Math.min(n, 4) }, (_, i) => (
        <li key={i} className="car-linea">
          <span className="esqueleto car-foto" />
          <div className="car-datos">
            <span className="esqueleto" style={{ height: 16, width: '70%' }} />
            <span className="esqueleto" style={{ height: 14, width: '30%', marginTop: 8 }} />
          </div>
        </li>
      ))}
    </ul>
  )
}

function Vacio({ categorias }) {
  return (
    <section className="car-vacio" aria-labelledby="car-vacio-t">
      <svg width="120" height="120" viewBox="0 0 120 120" fill="none" aria-hidden="true">
        <circle cx="60" cy="60" r="56" fill="var(--surface-2)" />
        <path d="M30 38h9l8 36a4 4 0 0 0 4 3h30a4 4 0 0 0 4-3l6-26H43" stroke="var(--ink-tenue)" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="54" cy="90" r="4" fill="var(--ink-tenue)" />
        <circle cx="78" cy="90" r="4" fill="var(--ink-tenue)" />
      </svg>
      <h1 id="car-vacio-t">Tu carrito está vacío</h1>
      <p>Agrega productos y aquí verás tu resumen antes de comprar.</p>
      <Link href="/buscar?nuevo=1" className="boton grande">
        Ver novedades
      </Link>
      {categorias.length > 0 && (
        <ul className="car-vacio-cats" aria-label="Categorías">
          {categorias.map((c) => (
            <li key={c.slug}>
              <Link href={`/categoria/${c.slug}`}>{c.nombre}</Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function Linea({ linea, fijar, quitar }) {
  const tope = Math.min(linea.stock_maximo ?? MAX, MAX)
  const excede = linea.stock_maximo != null && linea.stock_maximo > 0 && linea.cantidad > linea.stock_maximo
  return (
    <li className={`car-linea${linea.problema ? ' con-problema' : ''}`}>
      <Link href={`/producto/${linea.slug}`} className="car-foto" tabIndex={-1} aria-hidden="true">
        {linea.foto ? <img src={urlFoto(linea.foto)} alt="" width={96} height={96} loading="lazy" decoding="async" /> : <span>Sin foto</span>}
      </Link>
      <div className="car-datos">
        {linea.marca && <p className="car-marca">{linea.marca}</p>}
        <Link href={`/producto/${linea.slug}`} className="car-nombre">
          {linea.nombre}
        </Link>
        <p className="car-unitario">
          {soles(linea.precio_unitario) ?? 'Consultar precio'}
          {linea.precio_unitario && ' c/u'}
        </p>
        {linea.problema && (
          <p className="alerta aviso car-problema" role="alert">
            <Icono nombre="info" tam={16} /> <span>{linea.problema}</span>
          </p>
        )}
        {excede && (
          <button type="button" className="boton chico secundario car-ajustar" onClick={() => fijar(linea.producto, linea.stock_maximo)}>
            Ajustar a {linea.stock_maximo}
          </button>
        )}
        <div className="car-controles">
          <div className="acc-cantidad" role="group" aria-label={`Cantidad de ${linea.nombre}`}>
            <button
              type="button"
              onClick={() => fijar(linea.producto, linea.cantidad - 1)}
              aria-label={linea.cantidad <= 1 ? `Quitar ${linea.nombre}` : 'Una unidad menos'}
            >
              <Icono nombre={linea.cantidad <= 1 ? 'basura' : 'menos'} tam={18} />
            </button>
            <output aria-label={`${linea.cantidad} unidades`}>{linea.cantidad}</output>
            <button
              type="button"
              onClick={() => fijar(linea.producto, linea.cantidad + 1)}
              disabled={linea.cantidad >= tope}
              aria-label="Una unidad más"
            >
              <Icono nombre="mas" tam={18} />
            </button>
          </div>
          <button type="button" className="car-quitar" onClick={() => quitar(linea.producto)}>
            <Icono nombre="basura" tam={15} /> Quitar
          </button>
        </div>
      </div>
      <p className="car-subtotal">{soles(linea.subtotal) ?? '—'}</p>
    </li>
  )
}

export default function CarritoVista({ categorias = [] }) {
  const { items, resumen, calculando, listo, fijar, quitar, vaciar } = useCarrito()

  if (!listo) {
    return <Esqueleto n={2} />
  }
  if (items.length === 0) return <Vacio categorias={categorias} />

  const lineas = resumen?.lineas ?? []
  const puede = Boolean(resumen?.puede_comprar) && !calculando
  const motivo = !resumen
    ? 'Calculando tu carrito…'
    : resumen.problemas > 0
      ? 'Resuelve los avisos de tus productos para continuar.'
      : calculando
        ? 'Actualizando precios…'
        : null

  return (
    <>
      <div className="car-cabecera">
        <h1 className="titulo-pagina">Mi carrito</h1>
        <button type="button" className="car-vaciar" onClick={vaciar}>
          <Icono nombre="basura" tam={16} /> Vaciar carrito
        </button>
      </div>
      <div className="car-rejilla">
        <section aria-label="Productos de tu carrito" aria-busy={calculando}>
          {resumen ? (
            <ul className="car-lineas">
              {lineas.map((l) => (
                <Linea key={l.producto} linea={l} fijar={fijar} quitar={quitar} />
              ))}
            </ul>
          ) : (
            <Esqueleto n={items.length} />
          )}
        </section>
        <aside className="car-resumen" aria-label="Resumen de tu pedido">
          <h2>Resumen</h2>
          <dl>
            <div>
              <dt>Productos ({resumen?.cantidad_total ?? '…'})</dt>
              <dd>{resumen ? soles(resumen.subtotal) : '…'}</dd>
            </div>
            <div>
              <dt>Envío</dt>
              <dd className="car-nota-envio">Se calcula en el siguiente paso</dd>
            </div>
            <div className="car-total">
              <dt>Subtotal</dt>
              <dd>{resumen ? soles(resumen.subtotal) : '…'}</dd>
            </div>
          </dl>
          <p className="car-igv">Precios en soles con IGV incluido.</p>
          {motivo && (
            <p className="alerta aviso" role="status">
              <Icono nombre="info" tam={16} /> <span>{motivo}</span>
            </p>
          )}
          <Link href="/compra" className="boton grande" aria-disabled={!puede} tabIndex={puede ? undefined : -1}>
            Continuar con la compra
          </Link>
          <Link href="/" className="boton secundario">
            Seguir comprando
          </Link>
        </aside>
      </div>
    </>
  )
}
