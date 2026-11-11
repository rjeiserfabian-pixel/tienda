import ConsultaEstado from '@/components/servicio/ConsultaEstado'
import Icono from '@/components/Icono'
import Migas from '@/components/Migas'
import { obtenerConfiguracion } from '@/lib/api'
import { enlaceWhatsapp } from '@/lib/format'
import '../servicio-tecnico.css'

export const revalidate = 120

export async function generateMetadata() {
  const config = await obtenerConfiguracion().catch(() => null)
  const servicio = config?.servicio
  const descripcion =
    (servicio?.visible && servicio.texto) || 'Consulta en línea el estado de tu equipo en servicio técnico con el código de tu hoja de ingreso.'
  return {
    title: 'Servicio técnico',
    description: descripcion,
    alternates: { canonical: '/servicio-tecnico' },
  }
}

const PASOS = [
  {
    icono: 'tienda',
    titulo: 'Deja tu equipo',
    texto: 'Lo registramos y te entregamos una hoja de ingreso con un código QR.',
  },
  {
    icono: 'llave',
    titulo: 'Lo revisamos',
    texto: 'Nuestro técnico lo revisa y te avisa cómo sigue tu servicio.',
  },
  {
    icono: 'lupa',
    titulo: 'Sigue su avance',
    texto: 'Con tu código ves aquí en qué paso está tu equipo, cuando quieras.',
  },
]

export default async function ServicioTecnico() {
  const config = await obtenerConfiguracion().catch(() => null)
  const nombre = config?.nombre ?? 'la tienda'
  const servicio = config?.servicio ?? {}
  const ofreceServicio = Boolean(servicio.visible && servicio.titulo)
  const whatsapp = enlaceWhatsapp(`Hola, quisiera información del servicio técnico de ${nombre}.`, config?.contacto?.whatsapp)

  return (
    <main id="contenido" className="contenedor st-pagina">
      <Migas items={[{ nombre: 'Inicio', href: '/' }, { nombre: 'Servicio técnico' }]} />

      <header className="st-cabecera">
        <h1>{ofreceServicio ? servicio.titulo : 'Servicio técnico'}</h1>
        <p className="st-intro">
          {ofreceServicio && servicio.texto
            ? servicio.texto
            : 'Consulta aquí el estado de tu equipo con el código de tu hoja de ingreso.'}
        </p>
        {ofreceServicio && servicio.puntos?.length > 0 && (
          <ul className="st-puntos">
            {servicio.puntos.map((punto) => (
              <li key={punto}>
                <Icono nombre="check" tam={18} /> {punto}
              </li>
            ))}
          </ul>
        )}
        {whatsapp && (
          <a href={whatsapp} target="_blank" rel="noopener noreferrer" className="boton whatsapp">
            <Icono nombre="chat" tam={18} /> Consultar por WhatsApp
          </a>
        )}
      </header>

      <section className="st-tarjeta" aria-labelledby="titulo-consulta">
        <h2 id="titulo-consulta">Consulta el estado de tu equipo</h2>
        <ConsultaEstado />
      </section>

      <section aria-labelledby="titulo-pasos">
        <h2 id="titulo-pasos" className="st-subtitulo">
          Cómo funciona
        </h2>
        <ol className="st-pasos">
          {PASOS.map((paso, i) => (
            <li key={paso.titulo} className="st-paso">
              <span className="st-paso-icono">
                <Icono nombre={paso.icono} tam={22} />
              </span>
              <div>
                <h3>
                  <span className="st-paso-numero">{i + 1}</span> {paso.titulo}
                </h3>
                <p>{paso.texto}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>
    </main>
  )
}
