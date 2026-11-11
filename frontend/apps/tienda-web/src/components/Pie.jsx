import Link from 'next/link'
import { enlaceWhatsapp } from '@/lib/format'
import Logo from './Logo'

const REDES = [
  ['facebook', 'Facebook'],
  ['instagram', 'Instagram'],
  ['tiktok', 'TikTok'],
  ['youtube', 'YouTube'],
]

/** «987654321» → «tel:+987654321»: deja solo dígitos y «+» para el enlace de llamada. */
const enlaceTelefono = (t) => `tel:${String(t).replace(/[^\d+]/g, '')}`

/** Pie de página: marca, categorías, ayuda y contacto. Todo lo de la empresa viene de la configuración. */
export default function Pie({ menu, config }) {
  const nombre = menu.tienda.nombre
  const contacto = config?.contacto ?? {}
  const legal = config?.legal ?? {}
  const whatsapp = enlaceWhatsapp(`Hola, quisiera información de ${nombre}.`, contacto.whatsapp)
  const categorias = menu.familias.flatMap((f) => f.categorias).slice(0, 6)
  const redes = REDES.filter(([clave]) => config?.redes?.[clave])
  const hayContacto = contacto.telefono || contacto.correo || contacto.direccion || contacto.horario
  const enlacesLegales = [
    [legal.terminos_url, 'Términos y condiciones'],
    [legal.privacidad_url, 'Política de privacidad'],
    [legal.libro_reclamaciones_url, 'Libro de reclamaciones'],
  ].filter(([url]) => url)
  const razon = legal.nombre_comercial && legal.nombre_comercial !== legal.razon_social ? null : legal.razon_social
  return (
    <footer className="pie">
      <div className="contenedor pie-rejilla">
        <div className="pie-marca">
          <Logo nombre={nombre} logo={config?.logo} conNombre={config?.nombre_junto_al_logo} claro />
          {config?.descripcion && <p>{config.descripcion}</p>}
          {redes.length > 0 && (
            <ul className="pie-redes" aria-label="Redes sociales">
              {redes.map(([clave, etiqueta]) => (
                <li key={clave}>
                  <a href={config.redes[clave]} target="_blank" rel="noopener noreferrer">
                    {etiqueta}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
        <nav aria-label="Categorías">
          <h2>Comprar</h2>
          <ul>
            {categorias.map((c) => (
              <li key={c.slug}>
                <Link href={`/categoria/${c.slug}`}>{c.nombre}</Link>
              </li>
            ))}
            <li>
              <Link href="/buscar?nuevo=1">Novedades</Link>
            </li>
            {menu.secciones?.ofertas && (
              <li>
                <Link href="/ofertas">Ofertas</Link>
              </li>
            )}
            {menu.secciones?.armador && (
              <li>
                <Link href="/arma-tu-pc">Arma tu PC</Link>
              </li>
            )}
          </ul>
        </nav>
        {(
          <div>
            <h2>Ayuda</h2>
            <ul>
              <li>
                <Link href="/servicio-tecnico">Seguimiento de servicio técnico</Link>
              </li>
              <li>
                <Link href="/comparar">Comparar productos</Link>
              </li>
              {whatsapp && (
                <li>
                  <a href={whatsapp} target="_blank" rel="noopener noreferrer">
                    Escríbenos por WhatsApp
                  </a>
                </li>
              )}
              {enlacesLegales.map(([url, texto]) => (
                <li key={texto}>
                  <a href={url} target="_blank" rel="noopener noreferrer">
                    {texto}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
        {hayContacto && (
          <div>
            <h2>Contacto</h2>
            <ul>
              {contacto.telefono && (
                <li>
                  <a href={enlaceTelefono(contacto.telefono)}>{contacto.telefono}</a>
                </li>
              )}
              {contacto.correo && (
                <li>
                  <a href={`mailto:${contacto.correo}`}>{contacto.correo}</a>
                </li>
              )}
              {contacto.direccion && (
                <li>
                  {contacto.mapa_url ? (
                    <a href={contacto.mapa_url} target="_blank" rel="noopener noreferrer">
                      {contacto.direccion}
                    </a>
                  ) : (
                    contacto.direccion
                  )}
                </li>
              )}
              {contacto.horario && <li>{contacto.horario}</li>}
            </ul>
          </div>
        )}
      </div>
      <div className="pie-final">
        <div className="contenedor">
          <p>
            © {new Date().getFullYear()} {legal.nombre_comercial || nombre}
            {razon && legal.ruc ? ` · ${razon} · RUC ${legal.ruc}` : legal.ruc ? ` · RUC ${legal.ruc}` : ''}. Todos los derechos
            reservados. Los precios incluyen IGV salvo que se indique lo contrario.
          </p>
        </div>
      </div>
    </footer>
  )
}
