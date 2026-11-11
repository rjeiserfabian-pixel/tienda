import Link from 'next/link'
import ConsultaEstado from '@/components/servicio/ConsultaEstado'
import RefrescoSuave from '@/components/servicio/RefrescoSuave'
import Icono from '@/components/Icono'
import { obtenerConfiguracion } from '@/lib/api'
import { enlaceWhatsapp } from '@/lib/format'
import {
  ESTADOS_FINALES,
  ETAPAS,
  SALIDAS,
  etapaActual,
  fechaDia,
  fechaHora,
  obtenerEstadoServicio,
  telefonoLimpio,
} from '@/lib/servicio-tecnico'
import '../../servicio-tecnico.css'

// Dato privado por enlace secreto: siempre se arma en cada visita, nunca se guarda ni se comparte.
export const dynamic = 'force-dynamic'

export const metadata = {
  title: 'Estado de tu equipo',
  robots: { index: false, follow: false, nocache: true },
  referrer: 'no-referrer',
}

function SinResultado({ situacion }) {
  const textos = {
    no_encontrado: {
      titulo: 'No encontramos tu orden',
      texto: 'Revisa el código o vuelve a escanear el código QR de tu hoja de ingreso.',
    },
    limitado: {
      titulo: 'Demasiadas consultas',
      texto: 'Hiciste varias consultas seguidas. Espera un minuto e inténtalo de nuevo.',
    },
    error: {
      titulo: 'No pudimos consultar el estado ahora',
      texto: 'Es un problema nuestro, no de tu equipo. Inténtalo de nuevo en unos minutos.',
    },
  }
  const t = textos[situacion] ?? textos.error
  return (
    <main id="contenido" className="contenedor st-pagina">
      <section className="st-tarjeta st-sin-resultado" role="alert">
        <h1>{t.titulo}</h1>
        <p>{t.texto}</p>
        <ConsultaEstado />
      </section>
    </main>
  )
}

export default async function EstadoDelEquipo({ params }) {
  const { token } = await params
  const [resultado, config] = await Promise.all([
    obtenerEstadoServicio(token),
    obtenerConfiguracion().catch(() => null),
  ])
  if (resultado.situacion !== 'ok') return <SinResultado situacion={resultado.situacion} />

  const d = resultado.datos
  const clave = d.estado?.clave
  const posicion = etapaActual(clave)
  const esSalida = SALIDAS.includes(clave)
  const completo = clave === 'ENTREGADO' // el último paso ya se cumplió
  const final = ESTADOS_FINALES.includes(clave)
  const telefono = telefonoLimpio(d.empresa?.telefono)
  const whatsapp = enlaceWhatsapp(
    `Hola, consulto por mi equipo. Orden ${d.codigo}.`,
    config?.contacto?.whatsapp,
  )
  const historial = [...(d.linea_de_tiempo ?? [])].reverse()
  const promesa = fechaDia(d.fecha_promesa)
  const entrega = fechaDia(d.fecha_entrega)
  const garantiaHasta = fechaDia(d.garantia?.hasta)

  return (
    <main id="contenido" className="contenedor st-pagina">
      {!final && <RefrescoSuave />}

      <header className="st-cabecera st-cabecera-orden">
        <p className="st-empresa">{d.empresa?.nombre}</p>
        <h1>Orden {d.codigo}</h1>
        {d.equipo && <p className="st-equipo">{d.equipo}</p>}
      </header>

      <section className={`st-estado${esSalida ? ' salida' : ''}`} aria-live="polite" aria-labelledby="titulo-estado">
        <p className="st-estado-etiqueta" id="titulo-estado">
          <Icono nombre={esSalida ? 'info' : 'reloj'} tam={18} /> Estado actual
        </p>
        <p className="st-estado-titulo" data-estado={clave}>
          {d.estado?.titulo}
        </p>
        <p className="st-estado-texto">{d.estado?.descripcion}</p>
        {d.mensaje_del_taller && (
          <p className="st-mensaje">
            <strong>Mensaje del taller:</strong> {d.mensaje_del_taller}
          </p>
        )}
        <dl className="st-datos">
          {fechaHora(d.fecha_ingreso) && (
            <div>
              <dt>Ingresó el</dt>
              <dd>{fechaHora(d.fecha_ingreso)}</dd>
            </div>
          )}
          {promesa && (
            <div>
              <dt>Fecha estimada de entrega</dt>
              <dd>{promesa}</dd>
            </div>
          )}
          {entrega && (
            <div>
              <dt>Entregado el</dt>
              <dd>{entrega}</dd>
            </div>
          )}
          {historial[0] && fechaHora(historial[0].fecha) && (
            <div>
              <dt>Último movimiento</dt>
              <dd>{fechaHora(historial[0].fecha)}</dd>
            </div>
          )}
          {d.garantia && garantiaHasta && (
            <div>
              <dt>Garantía del servicio</dt>
              <dd>
                {d.garantia.dias} días, hasta el {garantiaHasta}
              </dd>
            </div>
          )}
        </dl>
        {d.es_garantia && <p className="st-nota">Esta atención es parte de la garantía de un servicio anterior.</p>}
      </section>

      {!esSalida && posicion >= 0 && (
        <section aria-labelledby="titulo-avance" className="st-tarjeta">
          <h2 id="titulo-avance">Avance de tu equipo</h2>
          <ol className="st-etapas">
            {ETAPAS.map((etapa, i) => {
              const estado = completo || i < posicion ? 'hecha' : i === posicion ? 'actual' : 'pendiente'
              return (
                <li key={etapa.id} className={`st-etapa ${estado}`} aria-current={estado === 'actual' ? 'step' : undefined}>
                  <span className="st-etapa-punto" aria-hidden="true">
                    {estado === 'hecha' ? <Icono nombre="check" tam={14} /> : i + 1}
                  </span>
                  <span className="st-etapa-texto">
                    {etapa.titulo}
                    <span className="sr-solo">
                      {estado === 'hecha' ? ' (listo)' : estado === 'actual' ? ' (en este paso)' : ' (pendiente)'}
                    </span>
                  </span>
                </li>
              )
            })}
          </ol>
        </section>
      )}

      {historial.length > 0 && (
        <section aria-labelledby="titulo-historial" className="st-tarjeta">
          <h2 id="titulo-historial">Historial</h2>
          <ol className="st-historial">
            {historial.map((p, i) => (
              <li key={`${p.titulo}-${p.fecha}-${i}`}>
                <strong>{p.titulo}</strong>
                {fechaHora(p.fecha) && <span>{fechaHora(p.fecha)}</span>}
              </li>
            ))}
          </ol>
        </section>
      )}

      <section className="st-tarjeta st-contacto" aria-labelledby="titulo-contacto">
        <h2 id="titulo-contacto">¿Tienes dudas?</h2>
        <p>Comunícate con nosotros y menciona tu orden <strong>{d.codigo}</strong>.</p>
        <div className="st-contacto-botones">
          {whatsapp && (
            <a href={whatsapp} target="_blank" rel="noopener noreferrer" className="boton whatsapp">
              <Icono nombre="chat" tam={18} /> Escribir por WhatsApp
            </a>
          )}
          {telefono && (
            <a href={`tel:${telefono}`} className="boton secundario">
              Llamar al {d.empresa.telefono}
            </a>
          )}
        </div>
        {d.empresa?.direccion && (
          <p className="st-direccion">
            <Icono nombre="pin" tam={16} /> {d.empresa.direccion}
          </p>
        )}
      </section>

      <p className="st-otra">
        ¿Otro equipo? <Link href="/servicio-tecnico">Consulta con otro código</Link>
      </p>
    </main>
  )
}
