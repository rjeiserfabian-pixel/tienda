'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'

/**
 * Productos elegidos para comparar. Viven en el navegador (localStorage), hasta 4.
 *
 * Solo se guardan datos para mostrar en la barra (id, nombre, foto y categoría); la comparación
 * en sí —precios, disponibilidad y datos técnicos— siempre la calcula el servidor al abrir /comparar.
 */
const CLAVE = 'tienda:comparar:v1'
export const MAX_COMPARAR = 4
const AVISO_MS = 4500

const ContextoComparar = createContext(null)
export const useComparar = () => useContext(ContextoComparar)

const texto = (valor, max) => (typeof valor === 'string' ? valor.slice(0, max) : '')

/** Deja solo elementos válidos y sin repetidos (lo guardado pudo ser alterado o venir de otra versión). */
function limpiar(lista) {
  if (!Array.isArray(lista)) return []
  const vistos = new Set()
  const salida = []
  for (const fila of lista) {
    const id = Number(fila?.id)
    if (!Number.isInteger(id) || id < 1 || vistos.has(id)) continue
    vistos.add(id)
    salida.push({
      id,
      nombre: texto(fila.nombre, 200),
      foto: typeof fila.foto === 'string' && fila.foto.startsWith('/api/v1/tienda/fotos/') ? fila.foto : null,
      categoria: texto(fila.categoria, 120),
    })
    if (salida.length === MAX_COMPARAR) break
  }
  return salida
}

function leer() {
  try {
    return limpiar(JSON.parse(window.localStorage.getItem(CLAVE) || '[]'))
  } catch {
    return []
  }
}

function escribir(items) {
  try {
    window.localStorage.setItem(CLAVE, JSON.stringify(items))
  } catch {
    // modo privado o sin espacio: la comparación sigue funcionando mientras la página esté abierta
  }
}

export default function ProveedorComparar({ children }) {
  const [items, setItems] = useState([])
  const [listo, setListo] = useState(false)
  const [aviso, setAviso] = useState('')
  const temporizador = useRef(null)

  useEffect(() => {
    setItems(leer())
    setListo(true)
    // otra pestaña cambió la lista
    const alCambiar = (e) => e.key === CLAVE && setItems(leer())
    window.addEventListener('storage', alCambiar)
    return () => {
      window.removeEventListener('storage', alCambiar)
      clearTimeout(temporizador.current)
    }
  }, [])

  useEffect(() => {
    if (listo) escribir(items)
  }, [items, listo])

  const avisar = useCallback((mensaje) => {
    setAviso(mensaje)
    clearTimeout(temporizador.current)
    temporizador.current = setTimeout(() => setAviso(''), AVISO_MS)
  }, [])

  /** `producto`: { id, nombre, foto, categoria: { slug } }. Devuelve si quedó agregado. */
  const agregar = useCallback(
    (producto) => {
      const id = Number(producto?.id)
      if (!Number.isInteger(id) || id < 1) return false
      if (items.some((i) => i.id === id)) return true
      if (items.length >= MAX_COMPARAR) {
        avisar(`Ya elegiste ${MAX_COMPARAR} productos. Quita uno para agregar otro.`)
        return false
      }
      const nuevo = limpiar([
        { id, nombre: producto.nombre, foto: producto.foto, categoria: producto.categoria?.slug ?? '' },
      ])[0]
      const otraCategoria = items.length > 0 && nuevo.categoria && items.some((i) => i.categoria && i.categoria !== nuevo.categoria)
      setItems([...items, nuevo])
      avisar(
        otraCategoria
          ? 'Es de otra categoría: solo se compararán los datos que tengan en común.'
          : `${nuevo.nombre || 'Producto'} agregado a la comparación.`,
      )
      return true
    },
    [items, avisar],
  )

  const quitar = useCallback((id) => setItems((actual) => actual.filter((i) => i.id !== id)), [])
  const limpiarTodo = useCallback(() => setItems([]), [])
  const tiene = useCallback((id) => items.some((i) => i.id === id), [items])

  const valor = useMemo(
    () => ({ items, listo, aviso, agregar, quitar, limpiar: limpiarTodo, tiene, lleno: items.length >= MAX_COMPARAR }),
    [items, listo, aviso, agregar, quitar, limpiarTodo, tiene],
  )

  return <ContextoComparar.Provider value={valor}>{children}</ContextoComparar.Provider>
}
