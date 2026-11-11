import Link from 'next/link'
import { notFound } from 'next/navigation'
import AccionesDeCompra from '@/components/AccionesDeCompra'
import BotonComparar from '@/components/BotonComparar'
import CuentaRegresiva from '@/components/CuentaRegresiva'
import Galeria from '@/components/Galeria'
import Icono from '@/components/Icono'
import JsonLd from '@/components/JsonLd'
import Migas from '@/components/Migas'
import SeccionProductos from '@/components/SeccionProductos'
import { consultarOpcional, obtenerConfiguracion, obtenerProducto } from '@/lib/api'
import { soles, textoDisponibilidad, urlAbsoluta } from '@/lib/format'
import '../../ofertas.css'
import '../../producto.css'

export const revalidate = 60

const DISPONIBILIDAD_SCHEMA = {
  disponible: 'https://schema.org/InStock',
  pocas: 'https://schema.org/LimitedAvailability',
  agotado: 'https://schema.org/OutOfStock',
}

const parrafos = (texto) =>
  String(texto ?? '')
    .split(/\n+/)
    .map((t) => t.trim())
    .filter(Boolean)

export async function generateMetadata({ params }) {
  const { slug } = await params
  const p = await consultarOpcional(obtenerProducto, slug).catch(() => null)
  if (!p) return { title: 'Producto no encontrado', robots: { index: false } }
  const descripcion = (p.seo?.descripcion || parrafos(p.descripcion).join(' ')).slice(0, 160)
  const foto = p.fotos[0]
  return {
    title: p.nombre,
    description: descripcion || `${p.nombre}. Compra en línea con garantía y envío a domicilio o recojo en tienda.`,
    alternates: { canonical: `/producto/${p.slug}` },
    openGraph: {
      type: 'website',
      title: p.nombre,
      description: descripcion || undefined,
      url: urlAbsoluta(`/producto/${p.slug}`),
      images: foto ? [{ url: urlAbsoluta(foto.grande), alt: p.nombre }] : undefined,
    },
  }
}

export default async function PaginaProducto({ params }) {
  const { slug } = await params
  const p = await consultarOpcional(obtenerProducto, slug)
  const config = await obtenerConfiguracion().catch(() => null)
  if (!p) notFound()

  const precio = soles(p.precio_mostrar)
  const agotado = p.disponibilidad === 'agotado'
  const claseDisp = agotado ? 'agotado' : p.disponibilidad === 'pocas' ? 'poco' : 'ok'
  const textoDescripcion = parrafos(p.descripcion)
  const hayMedidas = Object.values(p.medidas_cm ?? {}).some(Boolean)
  const migas = [
    { nombre: 'Inicio', href: '/' },
    { nombre: p.familia.nombre, href: `/familia/${p.familia.slug}` },
    { nombre: p.categoria.nombre, href: `/categoria/${p.categoria.slug}` },
    { nombre: p.nombre },
  ]

  const datosProducto = {
    '@context': 'https://schema.org',
    '@type': 'Product',
    name: p.nombre,
    sku: p.codigo,
    ...(p.numero_de_parte ? { mpn: p.numero_de_parte } : {}),
    ...(p.marca ? { brand: { '@type': 'Brand', name: p.marca.nombre } } : {}),
    ...(p.fotos.length ? { image: p.fotos.map((f) => urlAbsoluta(f.grande)) } : {}),
    ...(textoDescripcion.length ? { description: textoDescripcion.join(' ').slice(0, 500) } : {}),
    ...(p.consultar_precio
      ? {}
      : {
          offers: {
            '@type': 'Offer',
            url: urlAbsoluta(`/producto/${p.slug}`),
            price: p.precio_mostrar,
            priceCurrency: 'PEN',
            ...(p.oferta?.termina_en ? { priceValidUntil: p.oferta.termina_en.slice(0, 10) } : {}),
            availability: DISPONIBILIDAD_SCHEMA[p.disponibilidad] ?? DISPONIBILIDAD_SCHEMA.disponible,
            itemCondition: 'https://schema.org/NewCondition',
          },
        }),
  }

  return (
    <main id="contenido" className="contenedor pagina prod-pagina">
      <Migas items={migas} />
      <JsonLd datos={datosProducto} />

      <div className="prod-principal">
        <Galeria fotos={p.fotos} nombre={p.nombre} />

        <div className="prod-info">
          <div className="prod-etiquetas">
            {p.nuevo && <span className="insignia nuevo">Nuevo</span>}
            {p.destacado && <span className="insignia destacado">Destacado</span>}
          </div>
          {p.marca && (
            <Link href={`/marca/${p.marca.slug}`} className="prod-marca">
              {p.marca.nombre}
            </Link>
          )}
          <h1 className="prod-titulo">{p.nombre}</h1>
          <p className="prod-codigos">
            <span>
              Código <b>{p.codigo}</b>
            </span>
            {p.numero_de_parte && (
              <span>
                N.º de parte <b>{p.numero_de_parte}</b>
              </span>
            )}
          </p>

          <div className="prod-precio-caja">
            {precio ? (
              <p className="prod-precio">
                {p.precio_normal_mostrar && <s className="prod-precio-antes">{soles(p.precio_normal_mostrar)}</s>}
                <strong>{precio}</strong>
                {p.descuento_pct && <span className="prod-ahorro">-{p.descuento_pct} %</span>}
                {p.incluye_igv && <small>IGV incluido</small>}
              </p>
            ) : (
              <p className="prod-precio consultar">
                <strong>Consultar precio</strong>
                <small>Escríbenos y te cotizamos</small>
              </p>
            )}
            <span className={`insignia ${claseDisp}`}>
              {!agotado && <Icono nombre="check" tam={14} />} {textoDisponibilidad(p)}
            </span>
          </div>
          {p.oferta?.termina_en && (
            <>
              {p.oferta.etiqueta && <p className="prod-etiqueta-oferta">{p.oferta.etiqueta}</p>}
              <CuentaRegresiva terminaEn={p.oferta.termina_en} />
            </>
          )}

          {p.puntos_destacados.length > 0 && (
            <ul className="prod-puntos-lista">
              {p.puntos_destacados.map((punto) => (
                <li key={punto}>
                  <Icono nombre="check" tam={18} /> {punto}
                </li>
              ))}
            </ul>
          )}

          <div className="prod-comprar">
            <AccionesDeCompra producto={p} whatsapp={config?.contacto?.whatsapp} />
          </div>
          <div className="comparar-ficha">
            <BotonComparar
              variante="ficha"
              producto={{ id: p.id, nombre: p.nombre, foto: p.fotos[0]?.mini ?? null, categoria: p.categoria }}
            />
          </div>

          <ul className="prod-garantias">
            <li>
              <Icono nombre="camion" tam={20} />
              <span>Envío a domicilio o recojo en tienda</span>
            </li>
            <li>
              <Icono nombre="escudo" tam={20} />
              <span>{p.garantia_meses ? `Garantía de ${p.garantia_meses} meses` : 'Con garantía y comprobante de pago'}</span>
            </li>
          </ul>
        </div>
      </div>

      <nav className="prod-secciones-nav" aria-label="Secciones del producto">
        {textoDescripcion.length > 0 && <a href="#descripcion">Descripción</a>}
        {p.especificaciones.length > 0 && <a href="#especificaciones">Especificaciones</a>}
        <a href="#entrega">Garantía y entrega</a>
      </nav>

      {textoDescripcion.length > 0 && (
        <section className="prod-bloque" id="descripcion" aria-labelledby="t-descripcion">
          <h2 id="t-descripcion">Descripción</h2>
          <div className="prod-texto">
            {textoDescripcion.map((t, i) => (
              <p key={i}>{t}</p>
            ))}
          </div>
        </section>
      )}

      {p.especificaciones.length > 0 && (
        <section className="prod-bloque" id="especificaciones" aria-labelledby="t-especificaciones">
          <h2 id="t-especificaciones">Especificaciones</h2>
          <div className="prod-specs">
            {p.especificaciones.map((s) => (
              <section key={s.seccion} className="prod-spec-grupo" aria-label={s.seccion}>
                <h3>{s.seccion}</h3>
                <dl>
                  {s.datos.map((d) => (
                    <div key={d.nombre} className="prod-spec-fila">
                      <dt>{d.nombre}</dt>
                      <dd>{d.valor}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            ))}
          </div>
        </section>
      )}

      <section className="prod-bloque" id="entrega" aria-labelledby="t-entrega">
        <h2 id="t-entrega">Garantía y entrega</h2>
        <ul className="prod-entrega">
          <li>
            <Icono nombre="escudo" tam={22} />
            <div>
              <h3>Garantía</h3>
              <p>
                {p.garantia_meses
                  ? `Este producto tiene ${p.garantia_meses} meses de garantía. `
                  : 'Este producto tiene garantía. '}
                Te entregamos comprobante de pago con tu compra.
              </p>
            </div>
          </li>
          <li>
            <Icono nombre="camion" tam={22} />
            <div>
              <h3>Entrega</h3>
              <p>
                {config?.entrega_texto ||
                  'Elige envío a domicilio o recojo en tienda. Coordinamos contigo la fecha y el costo al confirmar tu pedido.'}
              </p>
            </div>
          </li>
          {(p.peso_kg || hayMedidas) && (
            <li>
              <Icono nombre="info" tam={22} />
              <div>
                <h3>Peso y medidas</h3>
                <p>
                  {p.peso_kg && <>Peso: {Number(p.peso_kg)} kg. </>}
                  {hayMedidas && (
                    <>
                      Medidas (largo × ancho × alto):{' '}
                      {[p.medidas_cm.largo, p.medidas_cm.ancho, p.medidas_cm.alto].map((m) => (m ? Number(m) : '—')).join(' × ')} cm.
                    </>
                  )}
                </p>
              </div>
            </li>
          )}
        </ul>
      </section>

      {p.relacionados.length > 0 && (
        <div className="prod-relacionados">
          <SeccionProductos
            id="relacionados"
            titulo="También te puede interesar"
            productos={p.relacionados}
            href={`/categoria/${p.categoria.slug}`}
            textoEnlace={`Más en ${p.categoria.nombre}`}
          />
        </div>
      )}

      <div className="prod-barra" role="region" aria-label="Comprar este producto">
        <div className="prod-barra-precio">
          <strong>{precio ?? 'Consultar precio'}</strong>
          {p.incluye_igv && precio && <small>IGV incluido</small>}
        </div>
        <AccionesDeCompra producto={p} whatsapp={config?.contacto?.whatsapp} compacto />
      </div>
    </main>
  )
}
