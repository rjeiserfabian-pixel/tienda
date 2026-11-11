'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { soles } from '@/lib/format'
import Icono from './Icono'

const MINIMO = 2
const ESPERA_MS = 200

/**
 * Buscador con sugerencias mientras se escribe. Sin JavaScript igual funciona (es un formulario que
 * va a /buscar). Con teclado: flechas para recorrer, Enter para abrir, Escape para cerrar.
 */
export default function Buscador({ etiqueta = 'Buscar productos', alNavegar }) {
  const router = useRouter()
  const id = useId()
  const raiz = useRef(null)
  const [texto, setTexto] = useState('')
  const [abierto, setAbierto] = useState(false)
  const [datos, setDatos] = useState(null)
  const [cargando, setCargando] = useState(false)
  const [activo, setActivo] = useState(-1)

  // Pide las sugerencias un momento después de que se deja de escribir y cancela las viejas.
  useEffect(() => {
    const t = texto.trim()
    if (t.length < MINIMO) {
      setDatos(null)
      setCargando(false)
      return undefined
    }
    const control = new AbortController()
    setCargando(true)
    const espera = setTimeout(async () => {
      try {
        const r = await fetch(`/api/v1/tienda/sugerencias?q=${encodeURIComponent(t)}`, { signal: control.signal })
        if (r.ok) setDatos(await r.json())
      } catch {
        // cancelada o sin conexión: se deja lo que había
      } finally {
        if (!control.signal.aborted) setCargando(false)
      }
    }, ESPERA_MS)
    return () => {
      clearTimeout(espera)
      control.abort()
    }
  }, [texto])

  // Se cierra al tocar fuera.
  useEffect(() => {
    const fuera = (e) => {
      if (raiz.current && !raiz.current.contains(e.target)) setAbierto(false)
    }
    document.addEventListener('pointerdown', fuera)
    return () => document.removeEventListener('pointerdown', fuera)
  }, [])

  const opciones = useMemo(() => {
    if (!datos) return []
    const lista = []
    for (const p of datos.productos) lista.push({ tipo: 'producto', href: `/producto/${p.slug}`, dato: p })
    for (const c of datos.categorias) lista.push({ tipo: 'categoria', href: `/categoria/${c.slug}`, dato: c })
    for (const m of datos.marcas) lista.push({ tipo: 'marca', href: `/marca/${m.slug}`, dato: m })
    lista.push({ tipo: 'todos', href: `/buscar?q=${encodeURIComponent(texto.trim())}`, dato: null })
    return lista
  }, [datos, texto])

  const ir = (href) => {
    setAbierto(false)
    alNavegar?.()
    router.push(href)
  }

  const alTeclear = (e) => {
    if (e.key === 'Escape') {
      setAbierto(false)
      setActivo(-1)
    } else if (e.key === 'ArrowDown' && opciones.length) {
      e.preventDefault()
      setAbierto(true)
      setActivo((a) => (a + 1) % opciones.length)
    } else if (e.key === 'ArrowUp' && opciones.length) {
      e.preventDefault()
      setActivo((a) => (a <= 0 ? opciones.length - 1 : a - 1))
    } else if (e.key === 'Enter' && abierto && activo >= 0 && opciones[activo]) {
      e.preventDefault()
      ir(opciones[activo].href)
    }
  }

  const alEnviar = (e) => {
    e.preventDefault()
    const t = texto.trim()
    if (t) ir(`/buscar?q=${encodeURIComponent(t)}`)
  }

  const listaId = `${id}-sugerencias`
  const mostrar = abierto && texto.trim().length >= MINIMO

  return (
    <div className="buscador" ref={raiz}>
      <form role="search" action="/buscar" method="get" onSubmit={alEnviar} className="buscador-form">
        <label htmlFor={`${id}-q`} className="sr-solo">
          {etiqueta}
        </label>
        <input
          id={`${id}-q`}
          name="q"
          type="search"
          autoComplete="off"
          placeholder="Busca laptops, mouse, monitores…"
          maxLength={80}
          value={texto}
          onChange={(e) => {
            setTexto(e.target.value)
            setAbierto(true)
            setActivo(-1)
          }}
          onFocus={() => setAbierto(true)}
          onKeyDown={alTeclear}
          role="combobox"
          aria-expanded={mostrar}
          aria-controls={listaId}
          aria-autocomplete="list"
          aria-activedescendant={activo >= 0 ? `${id}-op-${activo}` : undefined}
        />
        <button type="submit" className="buscador-boton" aria-label="Buscar">
          <Icono nombre="lupa" tam={20} />
        </button>
      </form>

      {mostrar && (
        <div className="buscador-panel" id={listaId} role="listbox" aria-label="Sugerencias">
          {cargando && !datos && <p className="buscador-estado">Buscando…</p>}
          {datos && opciones.length === 1 && (
            <p className="buscador-estado">No encontramos coincidencias. Prueba con otra palabra.</p>
          )}
          {opciones.map((o, i) => (
            <Link
              key={`${o.tipo}-${i}`}
              id={`${id}-op-${i}`}
              href={o.href}
              role="option"
              aria-selected={i === activo}
              className={`buscador-opcion ${o.tipo}${i === activo ? ' activa' : ''}`}
              onClick={() => {
                setAbierto(false)
                alNavegar?.()
              }}
              onMouseEnter={() => setActivo(i)}
            >
              {o.tipo === 'producto' && (
                <>
                  {o.dato.foto ? (
                    <img src={o.dato.foto.replace(/\/$/, '')} alt="" width={44} height={44} loading="lazy" decoding="async" />
                  ) : (
                    <span className="buscador-sin-foto" aria-hidden="true" />
                  )}
                  <span className="buscador-nombre">{o.dato.nombre}</span>
                  <span className="buscador-precio">{soles(o.dato.precio_mostrar) ?? 'Consultar'}</span>
                </>
              )}
              {o.tipo === 'categoria' && (
                <>
                  <Icono nombre="etiqueta" tam={18} />
                  <span className="buscador-nombre">
                    Categoría: <b>{o.dato.nombre}</b>
                  </span>
                </>
              )}
              {o.tipo === 'marca' && (
                <>
                  <Icono nombre="tienda" tam={18} />
                  <span className="buscador-nombre">
                    Marca: <b>{o.dato.nombre}</b>
                  </span>
                </>
              )}
              {o.tipo === 'todos' && (
                <>
                  <Icono nombre="lupa" tam={18} />
                  <span className="buscador-nombre">
                    Ver todos los resultados de «<b>{texto.trim()}</b>»
                  </span>
                </>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
