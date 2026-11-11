import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { api } from '../../../core/api/client'
import { fechaCorta } from '../../almacen/inventario'
import { fechaHora } from '../servicio'
import '../estado-publico.css'

/**
 * Lo que ve el cliente al escanear el QR de su hoja de ingreso: en qué va su equipo. No pide
 * sesión y solo muestra lo que el servidor deja ver (sin precios, sin diagnóstico, sin datos del cliente).
 */
export default function EstadoPublicoPage() {
  const { token } = useParams()
  const consulta = useQuery({
    queryKey: ['estado-publico', token],
    queryFn: ({ signal }) => api.get(`/servicio-tecnico/publico/${encodeURIComponent(token)}/`, { signal }).then((r) => r.data),
    retry: false,
    refetchInterval: 120_000,
  })
  const d = consulta.data

  return (
    <main className="estado-publico">
      <div className="estado-publico-caja">
        {consulta.isLoading && <p aria-busy="true">Buscando tu orden…</p>}
        {consulta.isError && (
          <div role="alert" className="estado-publico-error">
            <h1>No encontramos tu orden</h1>
            <p>{consulta.error?.response?.status === 404 ? 'Revisa el enlace o vuelve a escanear el código QR de tu hoja de ingreso.' : 'No pudimos consultar el estado ahora. Inténtalo de nuevo en unos minutos.'}</p>
            <button type="button" onClick={() => consulta.refetch()}>
              Reintentar
            </button>
          </div>
        )}
        {d && (
          <>
            <header>
              <span className="estado-publico-empresa">{d.empresa.nombre}</span>
              <h1>Orden {d.codigo}</h1>
              <p>{d.equipo}</p>
            </header>
            <section className="estado-publico-estado" aria-live="polite">
              <span className="estado-publico-etiqueta" data-estado={d.estado.clave}>
                {d.estado.titulo}
              </span>
              <p>{d.estado.descripcion}</p>
              {d.mensaje_del_taller && <p className="estado-publico-mensaje">{d.mensaje_del_taller}</p>}
              {d.fecha_promesa && <p className="estado-publico-dato">Fecha estimada de entrega: {fechaCorta(d.fecha_promesa)}</p>}
              {d.garantia && (
                <p className="estado-publico-dato">
                  Garantía: {d.garantia.dias} días, hasta el {fechaCorta(d.garantia.hasta)}.
                </p>
              )}
              {d.es_garantia && <p className="estado-publico-dato">Esta atención es parte de la garantía de un servicio anterior.</p>}
            </section>
            <section aria-label="Avance de tu equipo">
              <h2>Avance</h2>
              <ol className="estado-publico-tiempo">
                {[...d.linea_de_tiempo].reverse().map((p, i) => (
                  <li key={`${p.titulo}-${p.fecha}-${i}`}>
                    <strong>{p.titulo}</strong>
                    <span>{fechaHora(p.fecha)}</span>
                  </li>
                ))}
              </ol>
            </section>
            <footer>
              <p>
                ¿Dudas? {d.empresa.telefono ? <>Llámanos al <a href={`tel:${d.empresa.telefono}`}>{d.empresa.telefono}</a>.</> : 'Comunícate con el taller.'}
              </p>
              {d.empresa.direccion && <p>{d.empresa.direccion}</p>}
            </footer>
          </>
        )}
      </div>
    </main>
  )
}
