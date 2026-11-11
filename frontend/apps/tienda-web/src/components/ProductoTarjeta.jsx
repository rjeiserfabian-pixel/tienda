import Link from 'next/link'
import { soles, textoDisponibilidad } from '@/lib/format'
import '@/app/ofertas.css'
import BotonAgregar from './BotonAgregar'
import BotonComparar from './BotonComparar'
import CuentaRegresiva from './CuentaRegresiva'

/**
 * Tarjeta de un producto en los listados. Toda la tarjeta es UN enlace (más fácil de tocar y de
 * leer con un lector de pantalla). `prioridad` carga la foto de inmediato (solo para las primeras).
 */
export default function ProductoTarjeta({ producto: p, prioridad = false }) {
  const precio = soles(p.precio_mostrar)
  const agotado = p.disponibilidad === 'agotado'
  return (
    <article className="tar">
      <Link href={`/producto/${p.slug}`} className="tar-enlace">
        <div className="tar-foto">
          {p.foto ? (
            <img
              src={p.foto}
              alt=""
              width={400}
              height={400}
              loading={prioridad ? 'eager' : 'lazy'}
              fetchPriority={prioridad ? 'high' : 'auto'}
              decoding="async"
            />
          ) : (
            <span className="tar-sin-foto" aria-hidden="true">
              Sin foto
            </span>
          )}
          <div className="tar-etiquetas">
            {p.oferta && p.descuento_pct && <span className="insignia oferta">-{p.descuento_pct} %</span>}
            {p.oferta?.etiqueta && <span className="insignia oferta-etiqueta">{p.oferta.etiqueta}</span>}
            {p.nuevo && <span className="insignia nuevo">Nuevo</span>}
            {p.destacado && !p.nuevo && <span className="insignia destacado">Destacado</span>}
          </div>
        </div>
        <div className="tar-cuerpo">
          {p.marca && <p className="tar-marca">{p.marca.nombre}</p>}
          <h3 className="tar-nombre">{p.nombre}</h3>
          {p.tarjeta.length > 0 && (
            <ul className="tar-datos">
              {p.tarjeta.map((d) => (
                <li key={d.nombre}>
                  <span>{d.nombre}</span> <b>{d.valor}</b>
                </li>
              ))}
            </ul>
          )}
          {p.oferta?.termina_en && <CuentaRegresiva terminaEn={p.oferta.termina_en} compacta />}
          <div className="tar-pie">
            {precio ? (
              <p className="tar-precio">
                {p.precio_normal_mostrar && <s className="tar-precio-antes">{soles(p.precio_normal_mostrar)}</s>}
                <strong>{precio}</strong>
                {p.incluye_igv && <small>IGV incluido</small>}
              </p>
            ) : (
              <p className="tar-precio consultar">
                <strong>Consultar precio</strong>
              </p>
            )}
            <span className={`insignia ${agotado ? 'agotado' : p.disponibilidad === 'pocas' ? 'poco' : 'ok'}`}>
              {textoDisponibilidad(p)}
            </span>
          </div>
        </div>
      </Link>
      <BotonComparar producto={{ id: p.id, nombre: p.nombre, foto: p.foto, categoria: p.categoria }} />
      {precio && !agotado && (
        <div className="tar-accion">
          <BotonAgregar producto={p} />
        </div>
      )}
    </article>
  )
}
