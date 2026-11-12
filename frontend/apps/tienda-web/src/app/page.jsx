import Link from 'next/link'
import CarruselBanners from '@/components/CarruselBanners'
import Icono from '@/components/Icono'
import SeccionProductos from '@/components/SeccionProductos'
import { obtenerBanners, obtenerConfiguracion, obtenerInicio, obtenerMenu, obtenerProductos } from '@/lib/api'
import { enlaceWhatsapp, soles } from '@/lib/format'
import './inicio.css'

export const revalidate = 60

const MAX_COLLAGE = 3
const MAX_CATEGORIAS = 12

/** Destacados y novedades; si el negocio aún no marcó ninguno, se muestran los últimos productos. */
async function cargarProductos() {
  const inicio = await obtenerInicio()
  if (inicio.destacados.length || inicio.novedades.length) return inicio
  const lista = await obtenerProductos({ orden: 'nuevos', page_size: 8 })
  return { destacados: [], novedades: lista.results, ofertas: inicio.ofertas ?? [] }
}

export default async function Inicio() {
  const [menu, { destacados, novedades, ofertas = [] }, config, banners] = await Promise.all([
    obtenerMenu(),
    cargarProductos(),
    obtenerConfiguracion().catch(() => null),
    obtenerBanners().catch(() => []),
  ])
  const nombre = menu.tienda.nombre
  const whatsapp = enlaceWhatsapp(`Hola, quisiera información de ${nombre}.`, config?.contacto?.whatsapp)
  const portada = config?.portada ?? {}
  const servicio = config?.servicio ?? {}
  // El título de la portada resalta su última palabra (como antes); sin texto propio se usa el nombre.
  const beneficios = [
    config?.entrega_texto && { icono: 'camion', titulo: 'Envío o recojo', texto: config.entrega_texto },
    config?.garantia_texto && { icono: 'escudo', titulo: 'Garantía', texto: config.garantia_texto },
    servicio.visible && servicio.titulo && servicio.texto && { icono: 'llave', titulo: 'Servicio técnico', texto: servicio.texto },
    whatsapp && { icono: 'chat', titulo: 'Atención personalizada', texto: 'Escríbenos por WhatsApp y te ayudamos a elegir.' },
  ].filter(Boolean)
  // Las franjas de productos que sí tienen datos se alternan: oscura, clara, oscura… (así la página no es uniforme).
  const franjas = [ofertas, destacados, novedades].filter((lista) => lista.length > 0)
  const tonoDe = (lista) => (franjas.indexOf(lista) % 2 === 0 ? 'oscuro' : 'claro')
  const palabras = (portada.titulo || nombre).split(' ')
  const ultima = palabras.length > 1 ? palabras.pop() : null
  const categorias = menu.familias.flatMap((f) => f.categorias).slice(0, MAX_CATEGORIAS)

  // El collage del hero usa fotos reales; sin duplicados y solo con foto.
  const vistos = new Set()
  const collage = [...destacados, ...novedades]
    .filter((p) => p.foto && !vistos.has(p.id) && vistos.add(p.id))
    .slice(0, MAX_COLLAGE)

  return (
    <main id="contenido">
      <div className="contenedor ini-portada">
        {menu.familias.length > 0 && (
          <nav className="ini-lateral" aria-label="Categorías">
            <p className="ini-lateral-titulo">
              <Icono nombre="menu" tam={18} /> Categorías
            </p>
            <ul>
              {menu.familias.map((f) => (
                <li key={f.slug}>
                  <Link href={`/familia/${f.slug}`}>
                    <Icono nombre="etiqueta" tam={18} /> <span>{f.nombre}</span>
                    <Icono nombre="derecha" tam={16} />
                  </Link>
                </li>
              ))}
              {menu.secciones?.ofertas && (
                <li>
                  <Link href="/ofertas" className="ini-lateral-oferta">
                    <Icono nombre="etiqueta" tam={18} /> <span>Ofertas</span>
                    <Icono nombre="derecha" tam={16} />
                  </Link>
                </li>
              )}
            </ul>
          </nav>
        )}
        <div className="ini-portada-centro">
      {banners.length > 0 ? (
        <>
          <h1 className="sr-solo">{portada.titulo || nombre}</h1>
          <CarruselBanners banners={banners} />
        </>
      ) : (
        <section className="ini-hero" aria-label="Presentación">
          <div className="contenedor">
            <div className="ini-hero-caja">
              <div className="ini-hero-texto">
                {portada.etiqueta && <p className="ini-hero-etiqueta">{portada.etiqueta}</p>}
                <h1>
                  {palabras.join(' ')}
                  {ultima && (
                    <>
                      {' '}
                      <em>{ultima}</em>
                    </>
                  )}
                </h1>
                {portada.subtitulo && <p className="ini-hero-sub">{portada.subtitulo}</p>}
                <div className="ini-hero-botones">
                  <Link href="/buscar?nuevo=1" className="boton grande">
                    Ver novedades
                  </Link>
                  <a href="#categorias" className="boton secundario grande">
                    Explorar categorías
                  </a>
                </div>
              </div>
              {collage.length > 0 && (
                <div className={`ini-hero-visual${collage.length < 3 ? ' pocas' : ''}`} aria-label="Productos destacados">
                  {collage.map((p, i) => (
                    <Link key={p.id} href={`/producto/${p.slug}`} className="ini-hero-foto" aria-label={p.nombre}>
                      {i > 0 && soles(p.precio_mostrar) && <span className="ini-hero-chip">{soles(p.precio_mostrar)}</span>}
                      <img
                        src={p.foto}
                        alt=""
                        width={400}
                        height={400}
                        loading={i < 2 ? 'eager' : 'lazy'}
                        fetchPriority={i === 0 ? 'high' : 'auto'}
                        decoding="async"
                      />
                    </Link>
                  ))}
                </div>
              )}
            </div>
          </div>
        </section>
      )}
        </div>
      </div>

      {beneficios.length > 0 && (
        <section className="ini-seccion" aria-labelledby="titulo-beneficios">
          <div className="contenedor">
            <h2 id="titulo-beneficios" className="sr-solo">
              Por qué comprar con nosotros
            </h2>
            <ul className="ini-beneficios">
              {beneficios.map((b) => (
                <li key={b.titulo} className="ini-beneficio">
                  <span className="ini-beneficio-icono">
                    <Icono nombre={b.icono} tam={24} />
                  </span>
                  <div>
                    <h3>{b.titulo}</h3>
                    <p>{b.texto}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {categorias.length > 0 && (
        <section className="ini-seccion" id="categorias" aria-labelledby="titulo-categorias">
          <div className="contenedor">
            <div className="ini-seccion-cab">
              <h2 id="titulo-categorias">Compra por categoría</h2>
            </div>
            <ul className="ini-cats">
              {categorias.map((c) => (
                <li key={c.slug}>
                  <Link href={`/categoria/${c.slug}`} className="ini-cat">
                    <span className="ini-cat-icono">
                      <Icono nombre="etiqueta" tam={22} />
                    </span>
                    <span className="ini-cat-texto">
                      <strong>{c.nombre}</strong>
                      <small>{c.cantidad === 1 ? '1 producto' : `${c.cantidad} productos`}</small>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      <SeccionProductos
        id="ofertas"
        titulo="Ofertas"
        descripcion="Precios especiales por tiempo limitado."
        productos={ofertas}
        href="/ofertas"
        variante="destacada"
        tono={tonoDe(ofertas)}
      />

      <SeccionProductos
        id="destacados"
        titulo="Destacados"
        descripcion="Lo que más recomendamos."
        productos={destacados}
        href="/buscar?destacado=1"
        tono={tonoDe(destacados)}
      />

      <SeccionProductos
        id="novedades"
        titulo="Novedades"
        descripcion="Recién llegados a la tienda."
        productos={novedades}
        href="/buscar?nuevo=1"
        variante="rejilla"
        tono={tonoDe(novedades)}
      />

      {menu.marcas.length > 0 && (
        <section className="ini-seccion" aria-labelledby="titulo-marcas">
          <div className="contenedor">
            <div className="ini-seccion-cab">
              <h2 id="titulo-marcas">Nuestras marcas</h2>
            </div>
            <ul className="ini-marcas">
              {menu.marcas.map((m) => (
                <li key={m.slug}>
                  <Link href={`/marca/${m.slug}`}>
                    {m.nombre} <small>{m.cantidad}</small>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {servicio.visible && servicio.titulo && (
        <section className="ini-seccion" aria-labelledby="titulo-servicio">
          <div className="contenedor">
            <div className="ini-servicio">
              <div>
                <h2 id="titulo-servicio">{servicio.titulo}</h2>
                {servicio.texto && <p>{servicio.texto}</p>}
                {servicio.puntos?.length > 0 && (
                  <ul className="ini-servicio-lista">
                    {servicio.puntos.map((punto) => (
                      <li key={punto}>
                        <Icono nombre="check" tam={18} /> {punto}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              {whatsapp && (
                <a href={whatsapp} target="_blank" rel="noopener noreferrer" className="boton whatsapp grande">
                  <Icono nombre="chat" tam={20} /> Consultar por WhatsApp
                </a>
              )}
            </div>
          </div>
        </section>
      )}
    </main>
  )
}
