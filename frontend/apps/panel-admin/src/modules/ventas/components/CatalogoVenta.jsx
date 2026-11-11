import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api } from '../../../core/api/client'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import ImagenProtegida from '../../almacen/components/ImagenProtegida'
import { cantidad } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import { existenciaDe, precioDeLista, tienePrecio } from '../ventas'

// Solo se listan los primeros productos: para ver el resto se busca por nombre o código, o por categoría.
const FICHAS_VISIBLES = 8

const VISTAS = [
  ['productos', 'Productos'],
  ['categorias', 'Categorías'],
]

/** Una ficha del catálogo: foto, precio de la lista, cuánto hay en cada empresa y el botón Agregar. */
function Ficha({ p, lista, empresas, enCarrito, onAgregar }) {
  const precio = precioDeLista(p, lista)
  const sinPrecio = !tienePrecio(p, lista)
  const total = empresas.reduce((suma, e) => suma + existenciaDe(p, e.id), 0)
  const sinStock = p.controla_stock && total <= 0
  const bloqueado = sinPrecio || sinStock
  return (
    <article className={`pos-ficha${bloqueado ? ' agotada' : ''}`}>
      {p.foto_principal ? <ImagenProtegida className="pos-foto" url={`/mantenimiento/productos/${p.id}/fotos/${p.foto_principal}/imagen?tam=mini`} alt={`Foto de ${p.nombre}`} /> : <span className="pos-foto imagen-vacia" role="img" aria-label="Sin foto"><Icono nombre="package" tam={30} /></span>}
      <div className="pos-ficha-datos">
        <h4 title={p.nombre}>{p.nombre}</h4>
        <p className="celda-suave">{[p.marca, p.categoria].filter(Boolean).join(' · ') || p.codigo}</p>
        <strong className="pos-precio">{precio !== null && precio > 0 ? dinero(precio) : 'Sin precio'}</strong>
        <div className="pos-existencias" aria-label="Disponibilidad">
          {!p.controla_stock ? (
            <span className="pildora" data-tono="gris">Servicio</span>
          ) : (
            empresas.map((e) => {
              const n = existenciaDe(p, e.id)
              return (
                <span key={e.id} className="pildora" data-tono={n > 0 ? 'verde' : 'gris'} title={`${e.nombre}: ${n > 0 ? `${cantidad(n)} disponibles` : 'sin stock'}`}>
                  {e.letra} · {cantidad(n)}
                </span>
              )
            })
          )}
        </div>
      </div>
      <button type="button" className="primario pos-agregar" disabled={bloqueado} onClick={() => onAgregar(p)} aria-label={`Agregar ${p.nombre}`}>
        <Icono nombre="agregar" tam={18} /> {enCarrito ? 'Otra más' : 'Agregar'}
      </button>
      {sinPrecio && <small className="campo-error">No tiene precio en esta lista.</small>}
      {!sinPrecio && sinStock && <small className="campo-error">Sin stock.</small>}
    </article>
  )
}

/** Catálogo para vender: se escanea o escribe, se recorre por categorías y se agrega con un clic. */
export default function CatalogoVenta({ empresaId, categorias, lista, empresas, enCarrito, onAgregar, onAviso }) {
  const entrada = useRef(null)
  const cliente = useQueryClient()
  const [texto, setTexto] = useState('')
  const [vista, setVista] = useState('productos')
  const [categoria, setCategoria] = useState('')
  const q = useDebounce(texto.trim(), 300)
  // Al abrir, el cursor queda en el buscador sin mover la pantalla (si no, salta hasta él).
  useEffect(() => entrada.current?.focus({ preventScroll: true }), [])

  const pedir = (texto, categoria, signal) => api.get('/ventas/catalogo/', { params: { empresa: empresaId, q: texto, categoria: categoria || undefined }, signal }).then((r) => r.data)
  const clave = (texto, categoria) => ['ventas', 'catalogo', empresaId, texto, categoria]
  const consulta = useQuery({
    queryKey: clave(q, categoria),
    queryFn: ({ signal }) => pedir(q, categoria, signal),
    enabled: Boolean(empresaId) && vista === 'productos',
    staleTime: 10_000,
    placeholderData: (previo) => previo,
  })
  const fichas = (consulta.data?.results ?? []).slice(0, FICHAS_VISIBLES)

  // Un código escaneado (el lector termina con Enter) que coincide con un solo producto se agrega solo.
  const alEnter = async (e) => {
    if (e.key !== 'Enter') return
    e.preventDefault()
    const limpio = texto.trim()
    if (limpio.length < 2) return
    e.currentTarget.select()
    try {
      const datos = await cliente.fetchQuery({ queryKey: clave(limpio, ''), queryFn: ({ signal }) => pedir(limpio, '', signal), staleTime: 10_000 })
      if (datos.exacto && datos.results.length === 1) {
        onAgregar(datos.results[0])
        setTexto('')
      } else if (datos.results.length === 0) {
        onAviso?.(`No hay productos que coincidan con «${limpio}».`)
      }
    } catch {
      /* el listado de abajo muestra el error de la consulta */
    }
  }

  const elegirCategoria = (id) => {
    setCategoria(id)
    setVista('productos')
  }
  const nombreCategoria = categorias.find((c) => String(c.id) === String(categoria))?.nombre

  return (
    <section className="pos-catalogo" aria-label="Catálogo">
      <div className="consulta-buscador" role="search">
        <Icono nombre="scan" tam={24} />
        <input ref={entrada} type="search" autoComplete="off" aria-label="Buscar producto" placeholder="Escanea el código o escribe el nombre…" value={texto} onChange={(e) => { setTexto(e.target.value) }} onKeyDown={alEnter} />
        {texto && (
          <button type="button" onClick={() => { setTexto(''); entrada.current?.focus() }} aria-label="Limpiar búsqueda">
            Limpiar
          </button>
        )}
      </div>

      <div className="segmentos" role="tablist" aria-label="Vista del catálogo">
        {VISTAS.map(([valor, etiqueta]) => (
          <button key={valor} type="button" role="tab" aria-selected={vista === valor} className={vista === valor ? 'activo' : undefined} onClick={() => setVista(valor)}>
            {etiqueta}
          </button>
        ))}
        {categoria && vista === 'productos' && (
          <button type="button" className="pos-filtro-activo" onClick={() => elegirCategoria('')} title="Quitar el filtro">
            {nombreCategoria} ✕
          </button>
        )}
      </div>

      {vista === 'categorias' ? (
        <div className="pos-categorias">
          <button type="button" onClick={() => elegirCategoria('')}>
            <Icono nombre="layers" tam={22} /> Todas
          </button>
          {categorias.map((c) => (
            <button key={c.id} type="button" onClick={() => elegirCategoria(c.id)}>
              <Icono nombre="tags" tam={22} /> {c.nombre}
            </button>
          ))}
        </div>
      ) : (
        <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)} vacio="No hay productos para mostrar.">
          {fichas.length === 0 ? (
            <p className="estado-vacio">{q ? `No hay productos que coincidan con «${q}».` : 'No hay productos en el catálogo.'}</p>
          ) : (
            <div className="pos-rejilla" aria-live="polite">
              {fichas.map((p) => (
                <Ficha key={p.id} p={p} lista={lista} empresas={empresas} enCarrito={enCarrito.has(p.id)} onAgregar={onAgregar} />
              ))}
            </div>
          )}
        </EstadoConsulta>
      )}
    </section>
  )
}
