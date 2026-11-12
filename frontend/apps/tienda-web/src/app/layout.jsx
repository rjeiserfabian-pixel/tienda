import { Figtree, Sora } from 'next/font/google'
import AvisoCarrito from '@/components/AvisoCarrito'
import BarraInferior from '@/components/BarraInferior'
import BarraComparar from '@/components/BarraComparar'
import Cabecera from '@/components/Cabecera'
import Mantenimiento from '@/components/Mantenimiento'
import Pie from '@/components/Pie'
import ProveedorComparar from '@/components/ProveedorComparar'
import Proveedores from '@/components/Proveedores'
import { ErrorApi, obtenerConfiguracion, obtenerMenu } from '@/lib/api'
import { cssDelColor } from '@/lib/tema'
import './globals.css'
import './componentes.css'
import './formularios.css'
import './comparar.css'

const display = Sora({ subsets: ['latin'], variable: '--f-display', display: 'swap', weight: ['600', '700'] })
const cuerpo = Figtree({ subsets: ['latin'], variable: '--f-body', display: 'swap' })

/** El menú se pide una vez por página (queda en la caché de datos) y lo usan la cabecera y el pie. */
async function cargarMenu() {
  try {
    // La configuración (logo, contacto, textos) es de adorno: si falla, la tienda sigue con valores neutros.
    const [menu, config] = await Promise.all([obtenerMenu(), obtenerConfiguracion().catch(() => null)])
    return { menu, config }
  } catch (error) {
    return { error: error instanceof ErrorApi ? error : new ErrorApi(0, 'desconocido', 'Error inesperado') }
  }
}

export async function generateMetadata() {
  const { menu, config } = await cargarMenu()
  const nombre = menu?.tienda?.nombre ?? 'Tienda'
  const descripcion = config?.descripcion || `Compra en línea en ${nombre}. Envío a domicilio o recojo en tienda.`
  const base = process.env.SITE_URL || 'http://localhost:3000'
  return {
    metadataBase: new URL(base),
    title: { default: config?.descripcion ? `${nombre} | ${config.descripcion.split('.')[0]}` : nombre, template: `%s | ${nombre}` },
    description: descripcion,
    openGraph: { siteName: nombre, locale: 'es_PE', type: 'website' },
    robots: { index: true, follow: true },
  }
}

export const viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#070d24' },
    { media: '(prefers-color-scheme: dark)', color: '#050a1b' },
  ],
}

export default async function RootLayout({ children }) {
  const { menu, config, error } = await cargarMenu()
  const css = cssDelColor(config?.color)
  return (
    <html lang="es-PE" className={`${display.variable} ${cuerpo.variable}`}>
      <head>{css && <style dangerouslySetInnerHTML={{ __html: css }} />}</head>
      <body>
        {menu ? (
          <Proveedores>
            <ProveedorComparar>
            <a href="#contenido" className="saltar">
              Saltar al contenido
            </a>
            <Cabecera menu={menu} config={config} />
            {children}
            <Pie menu={menu} config={config} />
            <BarraComparar />
            <BarraInferior />
            <AvisoCarrito />
            </ProveedorComparar>
          </Proveedores>
        ) : (
          <Mantenimiento cerrada={error?.tiendaCerrada} />
        )}
      </body>
    </html>
  )
}
