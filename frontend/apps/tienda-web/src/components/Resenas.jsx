'use client'

import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import { ErrorTienda, llamar } from '@/lib/cliente'
import Estrellas from './Estrellas'
import { useCuenta } from './Proveedores'

const ORDENES = [
  { valor: 'recientes', texto: 'Más recientes' },
  { valor: 'mejores', texto: 'Mejor valoradas' },
  { valor: 'peores', texto: 'Peor valoradas' },
]

const fecha = (iso) => new Date(iso).toLocaleDateString('es-PE', { day: 'numeric', month: 'long', year: 'numeric' })

/** Elegir de 1 a 5 estrellas con el teclado o el mouse. */
function ElegirEstrellas({ valor, onCambio }) {
  return (
    <div className="res-elegir" role="radiogroup" aria-label="Tu puntaje">
      {[1, 2, 3, 4, 5].map((n) => (
        <label key={n} className={n <= valor ? 'activa' : ''}>
          <input type="radio" name="res-estrellas" value={n} checked={valor === n} onChange={() => onCambio(n)} />
          <svg width="30" height="30" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.4 6.1 20.5l1.2-6.5L2.5 9.4l6.6-.9z" fill={n <= valor ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
          </svg>
          <span className="sr-only">{n === 1 ? '1 estrella' : `${n} estrellas`}</span>
        </label>
      ))}
    </div>
  )
}

/** El formulario del cliente: solo aparece si ya recibió el producto. */
function MiOpinion({ slug, alGuardar }) {
  const cuenta = useCuenta()
  const [estado, setEstado] = useState(null) // { puede, mia, motivo }
  const [estrellas, setEstrellas] = useState(0)
  const [titulo, setTitulo] = useState('')
  const [comentario, setComentario] = useState('')
  const [editando, setEditando] = useState(false)
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState(null)

  const cargar = useCallback(async () => {
    try {
      const d = await llamar(`productos/${encodeURIComponent(slug)}/mi-resena`)
      setEstado(d)
      if (d.mia) {
        setEstrellas(d.mia.estrellas)
        setTitulo(d.mia.titulo)
        setComentario(d.mia.comentario)
      }
    } catch {
      setEstado(null)
    }
  }, [slug])

  useEffect(() => {
    if (cuenta?.autenticado) cargar()
  }, [cuenta?.autenticado, cargar])

  if (!cuenta || cuenta.estado === 'cargando') return null
  if (!cuenta.autenticado) {
    return (
      <p className="res-aviso">
        ¿Ya compraste este producto?{' '}
        <Link href={`/cuenta/ingresar?volver=${encodeURIComponent(`/producto/${slug}`)}`} className="enlace">
          Ingresa
        </Link>{' '}
        para dejar tu opinión.
      </p>
    )
  }
  if (!estado) return null
  if (!estado.puede && !estado.mia) return <p className="res-aviso">{estado.motivo}</p>

  async function guardar(evento) {
    evento.preventDefault()
    if (!estrellas) {
      setError('Elige de 1 a 5 estrellas.')
      return
    }
    setEnviando(true)
    setError(null)
    try {
      const d = await llamar(`productos/${encodeURIComponent(slug)}/mi-resena`, { metodo: 'PUT', cuerpo: { estrellas, titulo, comentario } })
      setEstado(d)
      setEditando(false)
      alGuardar()
    } catch (e) {
      setError(e instanceof ErrorTienda ? e.message : 'No pudimos guardar tu opinión. Inténtalo de nuevo.')
    } finally {
      setEnviando(false)
    }
  }

  async function borrar() {
    setEnviando(true)
    try {
      const d = await llamar(`productos/${encodeURIComponent(slug)}/mi-resena`, { metodo: 'DELETE' })
      setEstado(d)
      setEstrellas(0)
      setTitulo('')
      setComentario('')
      alGuardar()
    } catch (e) {
      setError(e instanceof ErrorTienda ? e.message : 'No pudimos borrar tu opinión.')
    } finally {
      setEnviando(false)
    }
  }

  if (estado.mia && !editando) {
    return (
      <div className="res-mia" role="status">
        <p>
          <strong>Tu opinión</strong> <Estrellas valor={estado.mia.estrellas} tam={16} />
        </p>
        {estado.mia.titulo && <p>{estado.mia.titulo}</p>}
        {estado.mia.comentario && <p>{estado.mia.comentario}</p>}
        {!estado.mia.visible && <p className="com-chico">Por ahora tu opinión no se muestra en la tienda.</p>}
        <div className="res-acciones">
          <button type="button" className="boton secundario chico" onClick={() => setEditando(true)}>
            Editar
          </button>
          <button type="button" className="boton fantasma chico" onClick={borrar} disabled={enviando}>
            Borrar
          </button>
        </div>
      </div>
    )
  }

  return (
    <form className="res-form" onSubmit={guardar} noValidate>
      <h3>{estado.mia ? 'Edita tu opinión' : 'Cuéntanos qué te pareció'}</h3>
      <p className="com-chico">Compraste este producto: tu opinión aparecerá como «compra verificada».</p>
      <ElegirEstrellas valor={estrellas} onCambio={setEstrellas} />
      <div className="campo">
        <label htmlFor="res-titulo">Título (opcional)</label>
        <input id="res-titulo" value={titulo} onChange={(e) => setTitulo(e.target.value)} maxLength={80} autoComplete="off" />
      </div>
      <div className="campo">
        <label htmlFor="res-comentario">Tu comentario (opcional)</label>
        <textarea id="res-comentario" rows={4} value={comentario} onChange={(e) => setComentario(e.target.value)} maxLength={1000} />
        <small className="com-chico">No se permiten enlaces. {comentario.length}/1000</small>
      </div>
      {error && (
        <p className="campo-error" role="alert">
          {error}
        </p>
      )}
      <div className="res-acciones">
        <button type="submit" className="boton" disabled={enviando}>
          {enviando ? 'Guardando…' : 'Publicar mi opinión'}
        </button>
        {editando && (
          <button type="button" className="boton fantasma" onClick={() => setEditando(false)}>
            Cancelar
          </button>
        )}
      </div>
    </form>
  )
}

/** Opiniones de compradores: promedio, desglose, lista y el formulario propio. */
export default function Resenas({ slug, inicial }) {
  const [datos, setDatos] = useState(inicial)
  const [orden, setOrden] = useState('recientes')
  const [cargando, setCargando] = useState(false)

  const recargar = useCallback(
    async (nuevoOrden = orden, pagina = 1, acumular = false) => {
      setCargando(true)
      try {
        const d = await llamar(`productos/${encodeURIComponent(slug)}/resenas?orden=${nuevoOrden}&page=${pagina}`)
        setDatos((anterior) => (acumular ? { ...d, results: [...anterior.results, ...d.results] } : d))
      } catch {
        // se mantiene lo que ya se veía
      } finally {
        setCargando(false)
      }
    },
    [slug, orden],
  )

  const r = datos?.resumen
  const hay = r && r.total > 0
  return (
    <section className="prod-bloque res" id="resenas" aria-labelledby="t-resenas">
      <h2 id="t-resenas">Opiniones de compradores</h2>
      {hay ? (
        <div className="res-cabecera">
          <div className="res-promedio">
            <strong>{r.promedio.toLocaleString('es-PE', { minimumFractionDigits: 1 })}</strong>
            <Estrellas valor={r.promedio} tam={22} />
            <span className="com-chico">
              {r.total} {r.total === 1 ? 'opinión' : 'opiniones'}
            </span>
          </div>
          <ul className="res-barras" aria-label="Cantidad de opiniones por puntaje">
            {['5', '4', '3', '2', '1'].map((n) => (
              <li key={n}>
                <span>{n} ★</span>
                <span className="res-barra" aria-hidden="true">
                  <span style={{ width: `${(r.distribucion[n] / r.total) * 100}%` }} />
                </span>
                <span className="com-chico">{r.distribucion[n]}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="com-chico">Todavía no hay opiniones de este producto.</p>
      )}

      <MiOpinion slug={slug} alGuardar={() => recargar()} />

      {hay && (
        <>
          <div className="res-orden">
            <label htmlFor="res-orden">Ordenar por</label>
            <select
              id="res-orden"
              value={orden}
              onChange={(e) => {
                setOrden(e.target.value)
                recargar(e.target.value)
              }}
            >
              {ORDENES.map((o) => (
                <option key={o.valor} value={o.valor}>
                  {o.texto}
                </option>
              ))}
            </select>
          </div>
          <ul className="res-lista">
            {datos.results.map((x) => (
              <li key={x.id}>
                <div className="res-linea">
                  <Estrellas valor={x.estrellas} tam={16} />
                  {x.titulo && <strong>{x.titulo}</strong>}
                </div>
                {x.comentario && <p className="res-texto">{x.comentario}</p>}
                <p className="com-chico">
                  {x.autor} · {fecha(x.fecha)} · <span className="res-verificada">Compra verificada</span>
                </p>
                {x.respuesta && (
                  <div className="res-respuesta">
                    <strong>Respuesta de la tienda</strong>
                    <p>{x.respuesta}</p>
                  </div>
                )}
              </li>
            ))}
          </ul>
          {datos.page < datos.paginas && (
            <button type="button" className="boton secundario" onClick={() => recargar(orden, datos.page + 1, true)} disabled={cargando}>
              {cargando ? 'Cargando…' : 'Ver más opiniones'}
            </button>
          )}
        </>
      )}
    </section>
  )
}
