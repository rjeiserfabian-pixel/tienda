import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api } from '../../../core/api/client'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import ImagenProtegida from '../../almacen/components/ImagenProtegida'
import { cantidad } from '../../almacen/inventario'
import { soles } from '../../almacen/utilidades'
import '../consulta.css'

const DEMORA = 300 // ms tras dejar de escribir; el Enter del escáner busca al instante

/** Un producto: foto, precios por lista y dónde hay stock (con su ubicación). Sin costos. */
function FichaProducto({ p, escaneada }) {
  const principal = p.precios.find((x) => x.es_principal) ?? p.precios[0]
  const otros = p.precios.filter((x) => x !== principal)
  return (
    <article className="consulta-ficha">
      {p.foto_principal ? (
        <ImagenProtegida className="consulta-foto" url={`/mantenimiento/productos/${p.id}/fotos/${p.foto_principal}/imagen?tam=mini`} alt={`Foto de ${p.nombre}`} />
      ) : (
        <span className="consulta-foto imagen-vacia" role="img" aria-label="Sin foto">
          <Icono nombre="package" tam={30} />
        </span>
      )}
      <div className="consulta-datos">
        <header>
          <h3>{p.nombre}</h3>
          <p className="celda-suave">
            {[p.marca, p.categoria].filter(Boolean).join(' · ')} · Código {p.codigo}
            {p.codigo_barras && p.codigo_barras !== p.codigo ? ` · Barras ${p.codigo_barras}` : ''}
          </p>
        </header>
        {principal ? (
          <div className="consulta-precio">
            <strong>{soles(principal.precio)}</strong>
            <span>{principal.nombre}</span>
          </div>
        ) : (
          <p className="celda-suave">Este producto aún no tiene precio.</p>
        )}
        {otros.length > 0 && (
          <ul className="consulta-listas" aria-label="Otras listas de precios">
            {otros.map((x) => (
              <li key={x.lista}>
                <span>{x.nombre}</span> <strong>{soles(x.precio)}</strong>
              </li>
            ))}
          </ul>
        )}
        {p.presentaciones?.length > 0 && (
          <ul className="consulta-presentaciones" aria-label="Precio por unidad">
            {p.presentaciones.map((pr) => {
              const precio = pr.precios.find((x) => x.es_principal) ?? pr.precios[0]
              return (
                <li key={pr.id} className={pr.id === escaneada ? 'escaneada' : undefined}>
                  <span>
                    <strong>{pr.unidad_nombre}</strong> <small className="celda-suave">trae {pr.factor} {p.unidad}</small>
                    {pr.id === escaneada && <span className="pildora" data-tono="verde">Escaneada</span>}
                  </span>
                  <strong>{precio ? soles(precio.precio) : 'Sin precio'}</strong>
                </li>
              )
            })}
          </ul>
        )}
        {p.lleva_serie && <p className="sub-texto">Lleva serie o IMEI: se registra al vender.</p>}
      </div>
      <Disponibilidad p={p} />
    </article>
  )
}

function Disponibilidad({ p }) {
  if (p.stock === null) return <div className="consulta-stock"><span className="pildora" data-tono="gris">Servicio</span></div>
  if (p.stock.length === 0) return <div className="consulta-stock"><p className="celda-suave">No tienes permiso para ver el stock.</p></div>
  const total = p.stock.reduce((s, e) => s + Number(e.cantidad), 0)
  return (
    <div className="consulta-stock" aria-label="Disponibilidad">
      <span className="pildora" data-tono={total > 0 ? 'verde' : 'rojo'}>
        {total > 0 ? `${cantidad(total)} ${p.unidad} disponibles` : 'Sin stock'}
      </span>
      {total > 0 && p.presentaciones?.length > 0 && (
        <p className="consulta-equivale">
          Equivale a:{' '}
          {p.presentaciones.map((pr) => {
            const factor = Number(pr.factor)
            const enteras = factor > 0 ? Math.floor(total / factor) : 0
            return `${enteras} ${pr.unidad_nombre.toLowerCase()}${enteras === 1 ? '' : 's'}`
          }).join(' · ')}
        </p>
      )}
      <ul>
        {p.stock.map((e) => (
          <li key={e.empresa}>
            <strong>{e.nombre}</strong>
            {e.almacenes ? (
              e.almacenes.length ? (
                e.almacenes.map((a) => (
                  <span key={a.almacen} className="consulta-almacen">
                    {a.almacen}: <b>{cantidad(a.cantidad)}</b>
                    {a.ubicacion_codigo && <span className="pildora" data-tono="azul" title={a.ubicacion_nombre}>{a.ubicacion_codigo}</span>}
                  </span>
                ))
              ) : (
                <span className="celda-suave">Sin stock</span>
              )
            ) : (
              <span className="consulta-almacen">
                <b>{cantidad(e.cantidad)}</b> en otra empresa
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Consulta rápida de precio, stock y ubicación: se escribe o se escanea y aparece todo. */
export default function ConsultaPreciosPage() {
  const entrada = useRef(null)
  const [texto, setTexto] = useState('')
  const [q, setQ] = useState('')

  useEffect(() => {
    const pasa = setTimeout(() => setQ(texto.trim()), DEMORA)
    return () => clearTimeout(pasa)
  }, [texto])
  useEffect(() => entrada.current?.focus(), [])

  const consulta = useQuery({
    queryKey: ['consulta-precios', q],
    queryFn: ({ signal }) => api.get('/inventario/consulta-precios/', { params: { q }, signal }).then((r) => r.data),
    enabled: q.length >= 2,
    staleTime: 15_000,
  })
  const resultados = consulta.data?.results ?? []

  const alEnter = (e) => {
    if (e.key !== 'Enter') return
    e.preventDefault()
    setQ(texto.trim())
    e.currentTarget.select() // el siguiente escaneo reemplaza lo anterior
  }
  const limpiar = () => {
    setTexto('')
    setQ('')
    entrada.current?.focus()
  }

  return (
    <main className="listado">
      <CabeceraListado icono="buscar" titulo="Consultar precios" descripcion="Escanea el código de barras o escribe el nombre: verás el precio, cuánto hay y dónde está." />

      <div className="consulta-buscador" role="search">
        <Icono nombre="scan" tam={24} />
        <input
          ref={entrada}
          type="search"
          autoComplete="off"
          aria-label="Buscar producto"
          placeholder="Escanea el código de barras o escribe el nombre…"
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          onKeyDown={alEnter}
        />
        {texto && (
          <button type="button" onClick={limpiar} aria-label="Limpiar búsqueda">
            Limpiar
          </button>
        )}
      </div>

      {q.length < 2 ? (
        <section className="consulta-inicio">
          <Icono nombre="scan" tam={40} />
          <h3>Listo para consultar</h3>
          <p>Pasa el producto por el lector o escribe al menos 2 letras del nombre o del código.</p>
        </section>
      ) : (
        <EstadoConsulta consulta={consulta} hayDatos={resultados.length > 0} vacio={`No hay productos que coincidan con «${q}».`}>
          {consulta.data?.exacto === false && resultados.length === 10 && <p className="celda-suave">Se muestran los 10 primeros. Escribe más del nombre para afinar.</p>}
          <div className="consulta-resultados" aria-live="polite">
            {resultados.map((p) => (
              <FichaProducto key={p.id} p={p} escaneada={consulta.data?.presentacion_escaneada} />
            ))}
          </div>
        </EstadoConsulta>
      )}
    </main>
  )
}
