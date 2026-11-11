import Link from 'next/link'
import ArmadorVista from '@/components/ArmadorVista'
import Icono from '@/components/Icono'
import JsonLd from '@/components/JsonLd'
import { consultar } from '@/lib/api'
import { urlAbsoluta } from '@/lib/format'
import '../armador.css'

export const revalidate = 60

const TITULO = 'Arma tu PC'
const DESCRIPCION =
  'Elige procesador, placa, memoria, almacenamiento y más con una guía que te avisa si las piezas son compatibles entre sí. Ve el total y agrégalo todo al carrito.'

async function cargarConfig() {
  try {
    return await consultar('armador/', undefined, { segundos: 60 })
  } catch {
    return { activo: false }
  }
}

export async function generateMetadata() {
  const config = await cargarConfig()
  if (!config.activo) return { title: TITULO, robots: { index: false, follow: true } }
  return {
    title: TITULO,
    description: DESCRIPCION,
    alternates: { canonical: '/arma-tu-pc' },
    openGraph: { title: TITULO, description: DESCRIPCION, url: urlAbsoluta('/arma-tu-pc'), type: 'website' },
  }
}

export default async function PaginaArmador() {
  const config = await cargarConfig()
  if (!config.activo) {
    return (
      <main id="contenido" className="contenedor pagina arm-proximamente">
        <Icono nombre="cpu" tam={44} />
        <h1>Arma tu PC, muy pronto</h1>
        <p>Estamos preparando una guía para que armes tu computadora con piezas compatibles entre sí. Mientras tanto, mira lo que tenemos.</p>
        <Link href="/buscar?nuevo=1" className="boton grande">
          Ver novedades
        </Link>
      </main>
    )
  }
  return (
    <main id="contenido" className="contenedor pagina arm-pagina">
      <JsonLd datos={{ '@context': 'https://schema.org', '@type': 'WebPage', name: TITULO, description: DESCRIPCION, url: urlAbsoluta('/arma-tu-pc') }} />
      <header className="arm-cab">
        <h1>{TITULO}</h1>
        <p>{DESCRIPCION}</p>
      </header>
      <ArmadorVista config={config} />
    </main>
  )
}
