import Link from 'next/link'
import { enlaceWhatsapp } from '@/lib/format'
import Buscador from './Buscador'
import CabeceraCuenta from './CabeceraCuenta'
import Icono from './Icono'
import Logo from './Logo'
import MenuCategorias from './MenuCategorias'
import MenuMovil from './MenuMovil'

const MARCAS_EN_EL_MENU = 5
const ICONOS_AVISO = ['camion', 'llave', 'escudo']

/** Cabecera de toda la tienda: aviso, marca, buscador y menú de categorías. */
export default function Cabecera({ menu, config }) {
  const nombre = menu.tienda.nombre
  const whatsapp = enlaceWhatsapp(`Hola, quisiera información de ${nombre}.`, config?.contacto?.whatsapp)
  const avisos = config?.avisos ?? []
  return (
    <>
      {avisos.length > 0 && (
        <div className="aviso" role="note">
          <div className="contenedor aviso-fila">
            {avisos.map((texto, i) => (
              <p key={texto} className={i === avisos.length - 1 && avisos.length > 1 ? 'aviso-derecha' : undefined}>
                <Icono nombre={ICONOS_AVISO[i % ICONOS_AVISO.length]} tam={16} /> {texto}
              </p>
            ))}
          </div>
        </div>
      )}
      <header className="cab">
        <div className="contenedor cab-fila">
          <MenuMovil familias={menu.familias} marcas={menu.marcas} nombre={nombre} />
          <Logo nombre={nombre} logo={config?.logo} conNombre={config?.nombre_junto_al_logo} />
          <div className="cab-buscar">
            <Buscador />
          </div>
          <div className="cab-acciones">
            <CabeceraCuenta />
            {whatsapp && (
              <a className="boton whatsapp chico" href={whatsapp} target="_blank" rel="noopener noreferrer">
                <Icono nombre="chat" tam={18} /> <span className="cab-texto-boton">WhatsApp</span>
              </a>
            )}
          </div>
        </div>
        <nav className="cab-nav" aria-label="Principal">
          <div className="contenedor cab-nav-fila">
            <MenuCategorias familias={menu.familias} />
            <Link href="/buscar?nuevo=1">Novedades</Link>
            <Link href="/buscar?destacado=1">Destacados</Link>
            {menu.secciones?.ofertas && (
              <Link href="/ofertas" className="cab-nav-oferta">
                Ofertas
              </Link>
            )}
            {menu.secciones?.armador && <Link href="/arma-tu-pc">Arma tu PC</Link>}
            <Link href="/servicio-tecnico">Servicio técnico</Link>
            {menu.marcas.slice(0, MARCAS_EN_EL_MENU).map((m) => (
              <Link key={m.slug} href={`/marca/${m.slug}`} className="cab-nav-marca">
                {m.nombre}
              </Link>
            ))}
          </div>
        </nav>
      </header>
    </>
  )
}
