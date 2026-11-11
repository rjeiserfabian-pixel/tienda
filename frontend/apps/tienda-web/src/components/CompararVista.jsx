'use client'

import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { llamar } from '@/lib/cliente'
import { soles, textoDisponibilidad, urlFoto } from '@/lib/format'
import Icono from './Icono'
import { MAX_COMPARAR, useComparar } from './ProveedorComparar'
import { useCarrito } from './Proveedores'

/** Ids válidos de la dirección (?ids=1,2,3): enteros positivos, sin repetir, hasta 4. */
function idsDeTexto(texto) {
  const ids = []
  for (const trozo of String(texto ?? '').split(',')) {
    const n = Number(trozo.trim())
    if (Number.isInteger(n) && n > 0 && !ids.includes(n)) ids.push(n)
  }
  return ids.slice(0, MAX_COMPARAR)
}

/**
 * Comparación lado a lado. La pide UNA vez a la API (`comparar?ids=`) cada vez que cambia la
 * lista. Si la dirección trae ids, esos mandan (así se puede compartir); si no, se usan los
 * productos elegidos en este navegador.
 */
export default function CompararVista() {
  const router = useRouter()
  const parametros = useSearchParams()
  const comparar = useComparar()
  const carrito = useCarrito()
  const idsUrl = useMemo(() => idsDeTexto(parametros.get('ids')), [parametros])
  const idsGuardados = useMemo(() => (comparar?.items ?? []).map((i) => i.id), [comparar?.items])
  const listoGuardado = comparar?.listo ?? false

  // Sin ids en la dirección y con productos elegidos: la dirección pasa a llevarlos (compartible).
  useEffect(() => {
    if (idsUrl.length === 0 && listoGuardado && idsGuardados.length > 0) {
      router.replace(`/comparar?ids=${idsGuardados.join(',')}`, { scroll: false })
    }
  }, [idsUrl, idsGuardados, listoGuardado, router])

  const ids = idsUrl
  const clave = ids.join(',')
  const [estado, setEstado] = useState('cargando') // cargando | listo | error
  const [datos, setDatos] = useState(null)
  const [mensajeError, setMensajeError] = useState('')
  const [soloDiferencias, setSoloDiferencias] = useState(false)
  const [intento, setIntento] = useState(0)

  useEffect(() => {
    if (ids.length === 0) {
      setDatos(null)
      setEstado(listoGuardado && idsGuardados.length === 0 ? 'listo' : 'cargando')
      return undefined
    }
    const control = new AbortController()
    setEstado('cargando')
    llamar(`comparar?ids=${clave}`, { signal: control.signal })
      .then((d) => {
        setDatos(d)
        setEstado('listo')
      })
      .catch((error) => {
        if (error?.name === 'AbortError') return
        setMensajeError(error?.message || 'No pudimos cargar la comparación.')
        setEstado('error')
      })
    return () => control.abort()
    // `clave` representa a `ids`
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clave, intento, listoGuardado])

  const quitar = useCallback(
    (id) => {
      comparar?.quitar(id)
      const resto = ids.filter((i) => i !== id)
      router.replace(resto.length ? `/comparar?ids=${resto.join(',')}` : '/comparar', { scroll: false })
    },
    [comparar, ids, router],
  )

  const productos = datos?.productos ?? []
  const secciones = useMemo(() => {
    const todas = datos?.secciones ?? []
    if (!soloDiferencias) return todas
    return todas.map((s) => ({ ...s, filas: s.filas.filter((f) => f.difiere) })).filter((s) => s.filas.length > 0)
  }, [datos, soloDiferencias])

  if (estado === 'cargando') return <Esqueleto />
  if (estado === 'error') {
    return (
      <div className="cmp-vacio">
        <p className="alerta error" role="alert">
          {mensajeError}
        </p>
        <button type="button" className="boton" onClick={() => setIntento((n) => n + 1)}>
          Reintentar
        </button>
      </div>
    )
  }
  if (productos.length < 2) return <Vacio hay={productos.length} avisos={datos?.avisos} />

  const columnas = productos.length
  return (
    <>
      <div className="cmp-barra">
        <label className="cmp-interruptor">
          <input type="checkbox" checked={soloDiferencias} onChange={(e) => setSoloDiferencias(e.target.checked)} />
          <span>Mostrar solo diferencias</span>
        </label>
        <p className="cmp-contador">
          Comparando {columnas} productos
        </p>
      </div>
      {!datos.misma_categoria && (
        <p className="alerta aviso" role="note">
          <Icono nombre="info" tam={18} /> Estás comparando productos de distintas categorías: solo se muestran los datos que tienen en común.
        </p>
      )}
      {datos.avisos?.map((a) => (
        <p key={a} className="alerta aviso" role="note">
          <Icono nombre="info" tam={18} /> {a}
        </p>
      ))}
      <p className="cmp-ayuda">Desliza la tabla hacia los lados para ver todos los productos →</p>
      <div className="cmp-contenedor" tabIndex={0} role="region" aria-label="Tabla comparativa de productos (desliza para ver más)">
        <table className="cmp-tabla" style={{ '--cmp-columnas': columnas }}>
          <caption className="sr-solo">Comparación de especificaciones entre {columnas} productos</caption>
          <thead>
            <tr>
              <th scope="col" className="cmp-esquina">
                <span className="sr-solo">Producto</span>
              </th>
              {productos.map((p) => (
                <th key={p.id} scope="col" className="cmp-producto">
                  <CabeceraProducto producto={p} alQuitar={() => quitar(p.id)} carrito={carrito} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {secciones.length === 0 && (
              <tr>
                <td className="cmp-nada" colSpan={columnas + 1}>
                  Estos productos tienen exactamente los mismos datos. Desactiva «Mostrar solo diferencias» para verlos.
                </td>
              </tr>
            )}
            {secciones.map((s) => (
              <FilasDeSeccion key={s.seccion} seccion={s} columnas={columnas} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function FilasDeSeccion({ seccion, columnas }) {
  return (
    <>
      <tr className="cmp-seccion">
        <th scope="colgroup" colSpan={columnas + 1}>
          <span>{seccion.seccion}</span>
        </th>
      </tr>
      {seccion.filas.map((f) => (
        <tr key={`${seccion.seccion}-${f.nombre}`} className={f.difiere ? 'difiere' : undefined}>
          <th scope="row" className="cmp-campo">
            {f.nombre}
            {f.difiere && <span className="sr-solo"> (difiere entre los productos)</span>}
          </th>
          {f.valores.map((v, i) => (
            <td key={i} className={`${v === null ? 'sin-dato' : ''}${f.mejor === i ? ' mejor' : ''}`}>
              {v ?? <span aria-label="Sin dato">—</span>}
            </td>
          ))}
        </tr>
      ))}
    </>
  )
}

function CabeceraProducto({ producto: p, alQuitar, carrito }) {
  const precio = soles(p.precio_mostrar)
  const agotado = p.disponibilidad === 'agotado'
  return (
    <div className="cmp-cab">
      <Link href={`/producto/${p.slug}`} className="cmp-foto" aria-label={`Ver ${p.nombre}`}>
        {p.foto ? <img src={urlFoto(p.foto)} alt="" width={160} height={160} decoding="async" /> : <span>Sin foto</span>}
      </Link>
      {p.marca && <p className="cmp-marca">{p.marca.nombre}</p>}
      <Link href={`/producto/${p.slug}`} className="cmp-nombre">
        {p.nombre}
      </Link>
      <p className="cmp-precio">
        {precio ? <strong>{precio}</strong> : <strong className="consultar">Consultar precio</strong>}
        {precio && p.incluye_igv && <small>IGV incluido</small>}
      </p>
      <span className={`insignia ${agotado ? 'agotado' : p.disponibilidad === 'pocas' ? 'poco' : 'ok'}`}>{textoDisponibilidad(p)}</span>
      <div className="cmp-acciones">
        {precio && !agotado && (
          <button
            type="button"
            className="boton chico"
            disabled={!carrito}
            onClick={() => carrito.agregar(p.id, 1, { nombre: p.nombre, foto: p.foto })}
          >
            <Icono nombre="carrito" tam={16} /> Agregar
          </button>
        )}
        <button type="button" className="boton fantasma chico" onClick={alQuitar} aria-label={`Quitar ${p.nombre} de la comparación`}>
          Quitar
        </button>
      </div>
    </div>
  )
}

function Vacio({ hay, avisos }) {
  return (
    <div className="cmp-vacio">
      <span className="cmp-vacio-icono" aria-hidden="true">
        <Icono nombre="comparar" tam={34} />
      </span>
      <h2>{hay === 1 ? 'Te falta un producto más' : 'Aún no elegiste productos para comparar'}</h2>
      <p>
        Para comparar necesitas al menos 2 productos (hasta {MAX_COMPARAR}). En los listados y en la ficha de cada producto toca{' '}
        <b>Comparar</b> y aquí verás sus datos lado a lado.
      </p>
      {avisos?.map((a) => (
        <p key={a} className="alerta aviso" role="note">
          {a}
        </p>
      ))}
      <div className="form-acciones">
        <Link href="/buscar?nuevo=1" className="boton">
          Ver novedades
        </Link>
        <Link href="/#categorias" className="boton secundario">
          Explorar categorías
        </Link>
      </div>
    </div>
  )
}

function Esqueleto() {
  return (
    <div className="cmp-esqueleto" aria-busy="true" aria-label="Cargando la comparación">
      <div className="esqueleto cmp-esq-cab" />
      <div className="esqueleto cmp-esq-fila" />
      <div className="esqueleto cmp-esq-fila" />
      <div className="esqueleto cmp-esq-fila" />
    </div>
  )
}
