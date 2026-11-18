import Link from 'next/link'
import ConsultaGarantia from '@/components/garantia/ConsultaGarantia'
import Icono from '@/components/Icono'
import { obtenerConfiguracion } from '@/lib/api'
import { enlaceWhatsapp } from '@/lib/format'
import { fechaDia, obtenerGarantia } from '@/lib/garantia'
import '../../servicio-tecnico.css'

// Dato privado por enlace secreto: siempre se arma en cada visita, nunca se guarda ni se comparte.
export const dynamic = 'force-dynamic'

export const metadata = {
  title: 'Tu garantía',
  robots: { index: false, follow: false, nocache: true },
  referrer: 'no-referrer',
}

function SinResultado({ situacion }) {
  const textos = {
    no_encontrado: {
      titulo: 'No encontramos tu garantía',
      texto: 'Revisa el código o vuelve a escanear el QR de tu certificado.',
    },
    limitado: {
      titulo: 'Demasiadas consultas',
      texto: 'Hiciste varias consultas seguidas. Espera un minuto e inténtalo de nuevo.',
    },
    error: {
      titulo: 'No pudimos consultar la garantía ahora',
      texto: 'Es un problema nuestro. Inténtalo de nuevo en unos minutos.',
    },
  }
  const t = textos[situacion] ?? textos.error
  return (
    <main id="contenido" className="contenedor st-pagina">
      <section className="st-tarjeta st-sin-resultado" role="alert">
        <h1>{t.titulo}</h1>
        <p>{t.texto}</p>
        <ConsultaGarantia />
      </section>
    </main>
  )
}

const TONO = { VIGENTE: 'verde', POR_VENCER: 'ambar', VENCIDA: 'rojo', ANULADA: 'gris', REEMPLAZADA: 'gris' }

export default async function TuGarantia({ params }) {
  const { token } = await params
  const [resultado, config] = await Promise.all([obtenerGarantia(token), obtenerConfiguracion().catch(() => null)])
  if (resultado.situacion !== 'ok') return <SinResultado situacion={resultado.situacion} />

  const d = resultado.datos
  const g = d.garantia
  const e = d.empresa
  const whatsapp = enlaceWhatsapp(`Hola, consulto por la garantía de mi ${d.producto.nombre}${d.producto.numero_serie ? ` (serie ${d.producto.numero_serie})` : ''}.`, config?.contacto?.whatsapp)

  return (
    <main id="contenido" className="contenedor st-pagina">
      <header className="st-cabecera st-cabecera-orden">
        <p className="st-empresa">{e.nombre}</p>
        <h1>Garantía de tu producto</h1>
        <p className="st-equipo">
          {d.producto.nombre}
          {d.producto.numero_serie ? ` · Serie ${d.producto.numero_serie}` : d.producto.unidades > 1 ? ` · ${d.producto.unidades} unidades` : ''}
        </p>
      </header>

      <section className={`st-estado${TONO[g.situacion] === 'gris' || TONO[g.situacion] === 'rojo' ? ' salida' : ''}`} aria-live="polite" aria-labelledby="titulo-estado">
        <p className="st-estado-etiqueta" id="titulo-estado">
          <Icono nombre={g.vigente ? 'check' : 'info'} tam={18} /> Estado de la garantía
        </p>
        <p className="st-estado-titulo" data-estado={g.situacion}>
          {g.texto}
        </p>
        {g.vigente && (
          <p className="st-estado-texto">
            Te quedan {g.dias_restantes} {g.dias_restantes === 1 ? 'día' : 'días'}.
          </p>
        )}
        <dl className="st-datos">
          <div>
            <dt>Comprobante</dt>
            <dd>{d.comprobante}</dd>
          </div>
          <div>
            <dt>Vale desde</dt>
            <dd>{fechaDia(g.desde)}</dd>
          </div>
          <div>
            <dt>Vale hasta</dt>
            <dd>{fechaDia(g.hasta)}</dd>
          </div>
          <div>
            <dt>Plazo</dt>
            <dd>
              {g.meses} {g.meses === 1 ? 'mes' : 'meses'}
            </dd>
          </div>
        </dl>
        {d.reclamo && (
          <p className="st-mensaje">
            <strong>Reclamo {d.reclamo.numero}:</strong> {d.reclamo.estado_texto} (abierto el {fechaDia(d.reclamo.fecha)}).
          </p>
        )}
      </section>

      <section className="st-tarjeta" aria-labelledby="titulo-condiciones">
        <h2 id="titulo-condiciones">Condiciones de la garantía</h2>
        <ul className="st-puntos">
          {d.condiciones.map((c) => (
            <li key={c}>
              <Icono nombre="check" tam={18} /> {c}
            </li>
          ))}
        </ul>
      </section>

      <section className="st-tarjeta" aria-labelledby="titulo-contacto">
        <h2 id="titulo-contacto">¿Necesitas hacer valer tu garantía?</h2>
        <p>
          Lleva tu producto y este certificado o tu comprobante a {e.nombre}
          {e.direccion ? ` (${e.direccion})` : ''}.
          {e.telefono ? ` Teléfono: ${e.telefono}.` : ''}
        </p>
        {whatsapp && (
          <a href={whatsapp} target="_blank" rel="noopener noreferrer" className="boton whatsapp">
            <Icono nombre="chat" tam={18} /> Consultar por WhatsApp
          </a>
        )}
        <p>
          <Link href="/garantia">Consultar otra garantía</Link>
        </p>
      </section>
    </main>
  )
}
