import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useRef, useState } from 'react'
import { api } from '../../core/api/client'
import { useDebounce } from '../hooks/useDebounce'
import { Icono } from './IconosPanel'
import './buscador-asincrono.css'

/**
 * Cuadro de búsqueda con lista de resultados que se piden al servidor mientras se escribe
 * (con retraso, para no pedir en cada tecla) y se cancelan si el texto cambia.
 *
 * Teclado: flechas para moverse, Enter para elegir y Escape para cerrar. Con un lector de códigos
 * basta escanear: el Enter llega antes que los resultados, así que queda pendiente y se elige el
 * primero apenas aparece. `mostrar(item)` dibuja cada opción; `onElegir(item)` recibe la elegida.
 */
export default function BuscadorAsincrono({
  clave,
  url,
  parametros,
  minimo = 2,
  etiqueta,
  placeholder,
  icono = 'buscar',
  mostrar,
  onElegir,
  limpiar = true,
  autoFocus = false,
  disabled = false,
  inputRef,
}) {
  const id = useId()
  const [texto, setTexto] = useState('')
  const [abierto, setAbierto] = useState(false)
  const [activo, setActivo] = useState(0)
  const cliente = useQueryClient()
  const escrito = useRef('') // último texto escrito: una respuesta tardía de otro texto no se elige
  const q = useDebounce(texto.trim(), 350)
  const vigente = texto.trim() === q
  const buscando = abierto && q.length >= minimo

  const pedir = (texto, signal) => api.get(url, { params: { q: texto, page_size: 8, ...parametros }, signal }).then((r) => r.data.results)
  const claveConsulta = (texto) => ['opciones', clave, texto, parametros ?? null]
  const consulta = useQuery({
    queryKey: claveConsulta(q),
    queryFn: ({ signal }) => pedir(q, signal),
    enabled: buscando,
    staleTime: 30_000,
  })
  const resultados = consulta.data ?? []
  const indice = Math.min(activo, Math.max(resultados.length - 1, 0))

  const elegir = (item) => {
    onElegir(item)
    setAbierto(false)
    setActivo(0)
    if (limpiar) setTexto('')
    inputRef?.current?.focus()
  }

  // Enter escrito antes de que lleguen los resultados (lector de códigos): se pide ya y se elige el primero.
  const elegirCuandoLlegue = async (texto) => {
    try {
      const lista = await cliente.fetchQuery({ queryKey: claveConsulta(texto), queryFn: ({ signal }) => pedir(texto, signal), staleTime: 30_000 })
      if (escrito.current === texto && lista[0]) elegir(lista[0])
    } catch {
      // el listado mostrará el error si la persona sigue escribiendo
    }
  }

  const alTeclear = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setAbierto(true)
      setActivo(Math.min(indice + 1, resultados.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActivo(Math.max(indice - 1, 0))
    } else if (e.key === 'Escape') {
      setAbierto(false)
    } else if (e.key === 'Enter') {
      e.preventDefault() // no envía el formulario
      if (texto.trim().length < minimo) return
      if (vigente && consulta.isSuccess) {
        if (resultados[indice]) elegir(resultados[indice])
      } else {
        elegirCuandoLlegue(texto.trim())
      }
    }
  }

  return (
    <div className="buscador-asincrono">
      <label className="sr-only" htmlFor={id}>
        {etiqueta}
      </label>
      <Icono nombre={icono} tam={20} className="buscador-asincrono-icono" />
      <input
        id={id}
        ref={inputRef}
        type="search"
        autoComplete="off"
        autoFocus={autoFocus}
        placeholder={placeholder}
        value={texto}
        disabled={disabled}
        role="combobox"
        aria-expanded={buscando}
        aria-controls={`${id}-lista`}
        aria-autocomplete="list"
        aria-activedescendant={buscando && resultados[indice] ? `${id}-${resultados[indice].id}` : undefined}
        onFocus={() => setAbierto(true)}
        onChange={(e) => {
          escrito.current = e.target.value.trim()
          setTexto(e.target.value)
          setAbierto(true)
          setActivo(0)
        }}
        onKeyDown={alTeclear}
        onBlur={() => setTimeout(() => setAbierto(false), 150)}
      />
      {buscando && (
        <ul id={`${id}-lista`} role="listbox" aria-label={etiqueta}>
          {(consulta.isLoading || !vigente) && <li className="sin-resultados">Buscando…</li>}
          {consulta.isError && <li className="sin-resultados">No se pudo buscar. Intenta de nuevo.</li>}
          {vigente && consulta.isSuccess && resultados.length === 0 && <li className="sin-resultados">Sin resultados para «{q}».</li>}
          {resultados.map((item, i) => (
            <li key={item.id} id={`${id}-${item.id}`} role="option" aria-selected={i === indice}>
              <button type="button" className={i === indice ? 'activa' : undefined} onMouseDown={(e) => e.preventDefault()} onMouseEnter={() => setActivo(i)} onClick={() => elegir(item)}>
                {mostrar(item)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
